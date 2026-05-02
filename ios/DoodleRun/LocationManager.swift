import CoreLocation
import Foundation

/// Thin wrapper around CLLocationManager that exposes the latest fix to
/// SwiftUI as `@Published` state. Requests "when in use" authorization on
/// first call to `requestCurrentLocation()`.
@MainActor
final class LocationManager: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var lastLocation: CLLocationCoordinate2D?
    @Published var authorizationStatus: CLAuthorizationStatus
    @Published var isResolving: Bool = false

    private let manager = CLLocationManager()

    override init() {
        self.authorizationStatus = manager.authorizationStatus
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func requestCurrentLocation() {
        switch manager.authorizationStatus {
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        case .restricted, .denied:
            // Caller can show a "go to Settings" prompt based on
            // authorizationStatus; nothing further to do here.
            return
        default:
            break
        }
        isResolving = true
        manager.requestLocation()
    }

    // MARK: - CLLocationManagerDelegate
    //
    // Delegate callbacks are marked `nonisolated` because Core Location calls
    // them from its internal queue. We bounce back to the main actor before
    // touching @Published state.

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.authorizationStatus = status
            if status == .authorizedWhenInUse || status == .authorizedAlways {
                manager.requestLocation()
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager,
                                     didUpdateLocations locations: [CLLocation]) {
        let coord = locations.last?.coordinate
        Task { @MainActor in
            self.isResolving = false
            self.lastLocation = coord
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager,
                                     didFailWithError error: Error) {
        Task { @MainActor in
            self.isResolving = false
        }
    }
}
