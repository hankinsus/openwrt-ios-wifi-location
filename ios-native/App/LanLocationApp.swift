// Modified location-only interface. AGPL-3.0.
// The default target links idevice. There is no substitute port.
import SwiftUI

@main
struct LanLocationApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView(controller: LocationController(port: IdeviceLocationCommandPort()))
        }
    }
}
