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
         session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session

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
