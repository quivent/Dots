import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

// Render the app's seven-dot mark directly into an opaque bitmap.
// Run from the repository root: swift ios/tools/render-icon.swift
let size = 1024
let space = CGColorSpaceCreateDeviceRGB()
let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                        bytesPerRow: size * 4, space: space,
                        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
let colors = [CGColor(red: 0.14, green: 0.22, blue: 0.67, alpha: 1),
              CGColor(red: 0.37, green: 0.47, blue: 0.96, alpha: 1)] as CFArray
let gradient = CGGradient(colorsSpace: space, colors: colors, locations: [0, 1])!
context.drawLinearGradient(gradient, start: CGPoint(x: 0, y: 0),
                           end: CGPoint(x: 1024, y: 1024), options: [])
let radius: CGFloat = 80
let spacing: CGFloat = 205
for index in 0..<7 {
    let angle = CGFloat(index) * .pi / 3 + .pi / 6
    let point = index == 6 ? CGPoint(x: 512, y: 512)
        : CGPoint(x: 512 + spacing * cos(angle), y: 512 + spacing * sin(angle))
    context.setFillColor(index == 6
        ? CGColor(red: 0.57, green: 0.96, blue: 0.89, alpha: 1)
        : CGColor(red: 1, green: 1, blue: 1, alpha: 0.96))
    context.fillEllipse(in: CGRect(x: point.x - radius, y: point.y - radius,
                                   width: radius * 2, height: radius * 2))
}
let output = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
    .deletingLastPathComponent().appendingPathComponent("Dots/Assets.xcassets/AppIcon.appiconset/AppIcon.png")
let destination = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(destination, context.makeImage()!, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("Could not save app icon") }
print("Rendered \(output.path)")
