import Foundation
import SwiftUI
import UIKit

/// Persists a GPX string to a temporary file and presents UIActivityViewController
/// so the user can save to Files, AirDrop, or open directly in Garmin Connect /
/// Strava (both register a UTI for .gpx files).
struct GPXShareSheet: UIViewControllerRepresentable {
    let gpxText: String
    let suggestedFileName: String

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let url = writeToTempFile()
        let vc = UIActivityViewController(activityItems: [url],
                                          applicationActivities: nil)
        vc.excludedActivityTypes = [.assignToContact, .addToReadingList]
        return vc
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController,
                                context: Context) {}

    private func writeToTempFile() -> URL {
        let dir = FileManager.default.temporaryDirectory
        let url = dir.appendingPathComponent(suggestedFileName)
        try? gpxText.write(to: url, atomically: true, encoding: .utf8)
        return url
    }
}
