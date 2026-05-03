import Foundation

/// Async HTTP client for the DoodleRun FastAPI service.
///
/// The base URL defaults to `http://localhost:8000` so the iOS Simulator can
/// hit a `uvicorn` process running on the host. On a physical device, replace
/// it with the LAN address of the dev machine (e.g. `http://192.168.1.42:8000`)
/// and add a matching ATS exception in Info.plist for HTTP traffic.
@MainActor
final class RouteService: ObservableObject {
    let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL = URL(string: "http://localhost:8000")!,
         session: URLSession? = nil) {
        self.baseURL = baseURL
        // v2_multi runs Optuna for 2–3 min on a fresh city; default URLSession
        // times out at 60 s and the user sees "request timed out" right when the
        // search is about to converge. Bump both timeouts to 5 min.
        if let session {
            self.session = session
        } else {
            let cfg = URLSessionConfiguration.default
            cfg.timeoutIntervalForRequest = 300
            cfg.timeoutIntervalForResource = 360
            self.session = URLSession(configuration: cfg)
        }

        let dec = JSONDecoder()
        dec.keyDecodingStrategy = .convertFromSnakeCase
        self.decoder = dec

        let enc = JSONEncoder()
        enc.keyEncodingStrategy = .convertToSnakeCase
        self.encoder = enc
    }

    func listShapes() async throws -> [ShapeMeta] {
        let url = baseURL.appendingPathComponent("shapes")
        let (data, response) = try await transport(URLRequest(url: url))
        try checkStatus(response, data: data)
        do {
            return try decoder.decode(ShapesResponse.self, from: data).shapes
        } catch {
            throw APIError.decoding(error)
        }
    }

    func generate(_ req: GenerateRequest) async throws -> GenerateResponse {
        let url = baseURL.appendingPathComponent("generate")
        var urlReq = URLRequest(url: url)
        urlReq.httpMethod = "POST"
        urlReq.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlReq.httpBody = try encoder.encode(req)

        let (data, response) = try await transport(urlReq)
        try checkStatus(response, data: data)
        do {
            return try decoder.decode(GenerateResponse.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    /// Stash the route on the server and get back a viewer URL the user can
    /// open in any mobile browser. Returns the absolute URL (baseURL + path).
    func share(_ req: ShareRequest) async throws -> URL {
        let url = baseURL.appendingPathComponent("share")
        var urlReq = URLRequest(url: url)
        urlReq.httpMethod = "POST"
        urlReq.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlReq.httpBody = try encoder.encode(req)

        let (data, response) = try await transport(urlReq)
        try checkStatus(response, data: data)
        let body: ShareResponse
        do {
            body = try decoder.decode(ShareResponse.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
        // Server returns a relative path like "/v/abc123" — prepend our base URL.
        return baseURL.appendingPathComponent(body.viewerUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }

    // MARK: - Helpers

    private func transport(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw APIError.transport(error)
        }
    }

    private func checkStatus(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            // FastAPI errors look like {"detail": "..."}. Surface that to the user
            // when present; otherwise just include the raw body.
            let detail = (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail
                ?? String(data: data, encoding: .utf8)
            throw APIError.badStatus(http.statusCode, detail)
        }
    }

    private struct ErrorBody: Decodable {
        let detail: String?
    }
}
