import Foundation
import SwiftUI
import UIKit

/// Bridges a UIActivityViewController for either a route file (GPX/KML) or a
/// shareable URL. Files are written to the temporary directory before being
/// passed in so apps that take a `fileURL` (Garmin Connect, Strava,
/// Google My Maps via Drive, etc.) get a real on-disk reference.
struct RouteShareSheet: UIViewControllerRepresentable {
    enum Payload {
        case textFile(content: String, fileName: String)
        case url(URL)
    }

    let payload: Payload

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let items: [Any]
        switch payload {
        case .textFile(let content, let fileName):
            items = [writeToTempFile(content, fileName: fileName)]
        case .url(let url):
            items = [url]
        }
        let vc = UIActivityViewController(activityItems: items,
                                          applicationActivities: nil)
        vc.excludedActivityTypes = [.assignToContact, .addToReadingList]
        return vc
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController,
                                context: Context) {}

    private func writeToTempFile(_ content: String, fileName: String) -> URL {
        let dir = FileManager.default.temporaryDirectory
        let url = dir.appendingPathComponent(fileName)
        try? content.write(to: url, atomically: true, encoding: .utf8)
        return url
    }
}
