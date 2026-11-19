# App icon

Layers for the new Liquid Glass app icon. The concept was made in Canva
(`concept-canva.png`); `preview.png` is a flat render of the two layers below.

| File | Layer |
| --- | --- |
| `background.svg` | Blue-to-indigo gradient fill, 1024 × 1024 |
| `glyph.svg` | White waveform turning into three lines of text, 1024 × 1024 |

## Making the `.icon` file

1. Open [Icon Composer](https://developer.apple.com/icon-composer/) (it comes with Xcode 26).
2. Create a new icon, then set its background to `background.svg`, or to a matching gradient fill.
3. Add `glyph.svg` as the foreground layer and turn on Liquid Glass for it.
   Check the Default, Dark and Tinted appearances.
4. Save it as `AppIcon.icon` in `macos/YTTranscribeApp/`, add it to the
   `YTTranscribeApp` target in Xcode, and select it as the app icon.

The app has no icon asset today, so this step must happen on a Mac.
