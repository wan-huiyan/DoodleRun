import SwiftUI
import CoreLocation
import MapKit

/// Top-level screen.
///
/// Layout (top → bottom):
///   - Map (snapped route + idealized outline + center pin, tap to move pin)
///   - Distance summary (target vs routed, % over)
///   - Distance slider (5–25 km)
///   - Shape picker (horizontally scrolling chips)
///   - "Generate Route" / "Use Current Location" / "Export GPX"
struct ContentView: View {
    // Default center: St Albans (the prototype's pig sample center).
    @State private var center = CLLocationCoordinate2D(latitude: 51.75, longitude: -0.34)
    @State private var distanceKm: Double = 10.0
    @State private var selectedShape: String = "pig"
    @State private var availableShapes: [ShapeMeta] = []
    @State private var routePolyline: [CLLocationCoordinate2D] = []
    @State private var idealOutline: [CLLocationCoordinate2D] = []
    @State private var lastResponse: GenerateResponse?
    @State private var isGenerating = false
    @State private var errorMessage: String?
    @State private var showShareSheet = false

    @StateObject private var routeService = RouteService()
    @StateObject private var locationManager = LocationManager()

    var body: some View {
        VStack(spacing: 0) {
            RouteMapView(
                center: $center,
                routePolyline: routePolyline,
                idealOutline: idealOutline
            )
            .frame(maxHeight: .infinity)

            controlPanel
                .background(.thinMaterial)
        }
        .task { await loadShapes() }
        .onChange(of: locationManager.lastLocation) { _, fix in
            if let fix { center = fix }
        }
        .alert("Couldn't generate route", isPresented: errorBinding) {
            Button("OK", role: .cancel) { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
        .sheet(isPresented: $showShareSheet) {
            if let gpx = lastResponse?.gpx {
                GPXShareSheet(
                    gpxText: gpx,
                    suggestedFileName: "\(selectedShape)_route.gpx"
                )
            }
        }
    }

    // MARK: - Subviews

    private var controlPanel: some View {
        VStack(spacing: 14) {
            if let r = lastResponse {
                HStack {
                    Text("Routed")
                        .font(.subheadline.weight(.semibold))
                    Text(String(format: "%.2f km", r.routedDistanceKm))
                        .font(.subheadline)
                    Spacer()
                    Text(String(format: "%+.1f%% vs target", r.errorPct))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal)
            }

            HStack {
                Text("Distance")
                Slider(value: $distanceKm, in: 5...25, step: 0.5)
                Text(String(format: "%.1f km", distanceKm))
                    .monospacedDigit()
                    .frame(width: 70, alignment: .trailing)
            }
            .padding(.horizontal)

            shapePicker

            HStack(spacing: 10) {
                Button {
                    locationManager.requestCurrentLocation()
                } label: {
                    Label("My Location", systemImage: "location.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(locationManager.isResolving)

                Button {
                    Task { await generate() }
                } label: {
                    if isGenerating {
                        ProgressView().tint(.white)
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Generate", systemImage: "scribble.variable")
                            .frame(maxWidth: .infinity)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isGenerating)
            }
            .padding(.horizontal)

            if lastResponse != nil {
                Button {
                    showShareSheet = true
                } label: {
                    Label("Export GPX", systemImage: "square.and.arrow.up")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .padding(.horizontal)
            }
        }
        .padding(.vertical, 14)
    }

    private var shapePicker: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(availableShapes) { shape in
                    Button {
                        selectedShape = shape.id
                    } label: {
                        VStack(spacing: 2) {
                            Text(shape.emoji).font(.title)
                            Text(shape.name)
                                .font(.caption.weight(.medium))
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(selectedShape == shape.id
                                      ? Color.accentColor.opacity(0.18)
                                      : Color.gray.opacity(0.10))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .strokeBorder(
                                    selectedShape == shape.id
                                        ? Color.accentColor
                                        : Color.clear,
                                    lineWidth: 2
                                )
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)
        }
    }

    // MARK: - Actions

    private func loadShapes() async {
        do {
            availableShapes = try await routeService.listShapes()
            if !availableShapes.contains(where: { $0.id == selectedShape }),
               let first = availableShapes.first {
                selectedShape = first.id
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func generate() async {
        isGenerating = true
        defer { isGenerating = false }
        let req = GenerateRequest(
            shape: selectedShape,
            lat: center.latitude,
            lon: center.longitude,
            distanceKm: distanceKm,
            waypoints: nil,
            iterations: nil
        )
        do {
            let resp = try await routeService.generate(req)
            lastResponse = resp
            routePolyline = resp.geojson.locationCoordinates
            idealOutline = resp.idealWaypoints
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { errorMessage != nil },
            set: { if !$0 { errorMessage = nil } }
        )
    }
}

#Preview {
    ContentView()
}
