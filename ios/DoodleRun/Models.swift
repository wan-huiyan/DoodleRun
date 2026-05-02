import Foundation
import CoreLocation

/// CLLocationCoordinate2D is a plain C struct without Equatable. SwiftUI's
/// .onChange / @Published diffing both need it, so we add the obvious
/// component-wise comparison here. `@retroactive` silences the Swift 6
/// warning about extending an external type with a system protocol.
#if compiler(>=6.0)
extension CLLocationCoordinate2D: @retroactive Equatable {
    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.latitude == rhs.latitude && lhs.longitude == rhs.longitude
    }
}
#else
extension CLLocationCoordinate2D: Equatable {
    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.latitude == rhs.latitude && lhs.longitude == rhs.longitude
    }
}
#endif

/// Mirrors the FastAPI service's Pydantic schemas. Field names must match
/// the JSON keys exactly — Swift's snake_case ↔ camelCase conversion is
/// handled by the JSONDecoder configuration in RouteService.

struct ShapeMeta: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let emoji: String
    let distinctiveFeatures: String
}

struct ShapesResponse: Decodable {
    let shapes: [ShapeMeta]
}

struct GenerateRequest: Encodable {
    let shape: String
    let lat: Double
    let lon: Double
    let distanceKm: Double
    let waypoints: Int?
    let iterations: Int?
}

/// GeoJSON-shaped: coordinates are [lon, lat] (NOT [lat, lon]).
struct GeoJSONLineString: Decodable {
    let type: String
    let coordinates: [[Double]]

    /// Convert to CoreLocation pairs (which use lat, lon order).
    var locationCoordinates: [CLLocationCoordinate2D] {
        coordinates.compactMap { pair in
            guard pair.count == 2 else { return nil }
            return CLLocationCoordinate2D(latitude: pair[1], longitude: pair[0])
        }
    }
}

struct GenerateResponse: Decodable {
    let shape: String
    let targetDistanceM: Double
    let routedDistanceM: Double
    let errorPct: Double
    let geojson: GeoJSONLineString
    let waypoints: [[Double]]    // [lat, lon] pairs
    let gpx: String

    var routedDistanceKm: Double { routedDistanceM / 1000.0 }
    var idealWaypoints: [CLLocationCoordinate2D] {
        waypoints.compactMap { pair in
            guard pair.count == 2 else { return nil }
            return CLLocationCoordinate2D(latitude: pair[0], longitude: pair[1])
        }
    }
}

/// Surfaces user-friendly messages for HTTP / decoding / network errors.
enum APIError: LocalizedError {
    case badStatus(Int, String?)
    case transport(Error)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .badStatus(let code, let detail):
            if let detail, !detail.isEmpty { return "Server error \(code): \(detail)" }
            return "Server error \(code)"
        case .transport(let e):
            return "Network error: \(e.localizedDescription)"
        case .decoding(let e):
            return "Couldn't read server response: \(e.localizedDescription)"
        }
    }
}
