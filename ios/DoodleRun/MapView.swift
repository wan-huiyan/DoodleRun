import SwiftUI
import MapKit
import CoreLocation

/// Map panel that shows the chosen center pin, the snapped run route (blue),
/// and the idealized animal outline (red dashed) once a route has been
/// generated. Tapping the map updates the binding so the user can pick a
/// custom start point.
///
/// Requires iOS 17 — uses the new `Map` content closure with `MapPolyline`
/// and `Annotation`. Falls back gracefully on tap with a single TapGesture
/// reading screen coordinates and reverse-projecting via `MapProxy`.
struct RouteMapView: View {
    @Binding var center: CLLocationCoordinate2D
    let routePolyline: [CLLocationCoordinate2D]
    let idealOutline: [CLLocationCoordinate2D]

    @State private var cameraPosition: MapCameraPosition = .automatic

    var body: some View {
        MapReader { proxy in
            Map(position: $cameraPosition) {
                Annotation("Start", coordinate: center) {
                    Image(systemName: "mappin.circle.fill")
                        .font(.title)
                        .foregroundStyle(.green)
                        .background(Circle().fill(.white))
                }

                if !idealOutline.isEmpty {
                    MapPolyline(coordinates: idealOutline)
                        .stroke(.red.opacity(0.65),
                                style: StrokeStyle(lineWidth: 2, dash: [6, 6]))
                }

                if !routePolyline.isEmpty {
                    MapPolyline(coordinates: routePolyline)
                        .stroke(.blue, lineWidth: 5)
                }
            }
            .mapStyle(.standard(elevation: .flat))
            .onTapGesture(coordinateSpace: .local) { screenPoint in
                if let tapped = proxy.convert(screenPoint, from: .local) {
                    center = tapped
                }
            }
            .onChange(of: routePolyline.count) { _, newCount in
                // Frame the route once a generation completes.
                if newCount > 0 {
                    cameraPosition = .automatic
                }
            }
        }
    }
}
