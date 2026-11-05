# EXRP logo guidelines

![EXRP logo](png/exrp-horizontal-color-1600.png)

## 1. The logo
**Idea:** a speech bubble that is also a switch: say it, and it's set. The bubble is the conversation, and the mint knob is the live setting it changes.

| Version | Use it for | File |
|---|---|---|
| Horizontal (primary) | Websites, product headers, documents | `lockups/exrp-horizontal-*.svg` |
| Stacked | Square or narrow spaces, signage | `lockups/exrp-stacked-*.svg` |
| Symbol | App icons, avatars, tight spaces | `symbol/exrp-symbol-*.svg` |
| Small symbol | 24 px and below only | `symbol/exrp-symbol-small*.svg` |
| Wordmark | Where the symbol already appears nearby | `wordmark/exrp-wordmark-*.svg` |

Write the name as **EXRP** in running text. The lowercase form appears only in the logo artwork.

## 2. Clear space
Keep one **knob width** (the diameter of the round knob) clear on every side of the logo. It scales with the logo, so never use a fixed distance.

## 3. Minimum size
| Version | Screen | Print |
|---|---|---|
| Horizontal | 96 px wide | 25 mm wide |
| Stacked | 64 px wide | 18 mm wide |
| Symbol | 32 px | 8 mm |
| Small symbol | 16 px | 5 mm |

The print sizes are starting points and haven't been tested on paper yet.

## 4. Colour
| Name | HEX | RGB | CMYK (approx.) | Pantone (approx.) | Use |
|---|---|---|---|---|---|
| Pine | `#0B3D36` | 11 61 54 | 82 0 11 76 | 3308 C | Bubble, wordmark, dark backgrounds |
| Mint | `#35E3A1` | 53 227 161 | 77 0 29 11 | 7479 C | Knob, bubble on dark backgrounds |

CMYK values are direct conversions and the Pantone values are suggested starting points. Check both against a printed proof and a physical Pantone guide. Mint is likely to print duller in CMYK, so use a spot colour where it has to stay vivid.

**Approved combinations**

| Background | Artwork | File suffix |
|---|---|---|
| White or light | Pine bubble with mint knob, pine wordmark | `-color` |
| Pine or very dark | Mint bubble, white wordmark | `-reversed` |
| Pine, dark or photo | All white | `-white` |
| One-colour print on light | All pine or all black | `-pine`, `-black` |

Measured contrast: pine on white 12.1:1, mint on pine 7.3:1, mint on white 1.7:1. **Never use mint alone on white.**

Reversed artwork has a slightly larger knob to offset the way light shapes look heavier on dark backgrounds, so use those files instead of recolouring the standard ones.

## 5. Typography
The wordmark is custom-drawn, so never retype it in a font. For supporting text, **Inter** is a suggested pairing (SIL Open Font License), with a system sans-serif as the web fallback.

## 6. Don'ts
- Don't stretch, squash, rotate or mirror the logo. The knob always stays on the right, in the "on" position.
- Don't recolour outside the palette, or swap the pine and mint in the full-colour version.
- Don't add shadows, outlines, gradients or effects.
- Don't rearrange or resize the parts of a lockup.
- Don't use the standard symbol below 32 px or the small symbol above 24 px.
- Don't place the logo on a busy background. Use a calm area or a pine tile.

## 7. Web icons
Copy the contents of `web-icons/` to your site's root folder and paste `web-icons/head-snippet.html` into the page `<head>`.

## 8. Files
| Folder | Contents |
|---|---|
| `symbol/` | Symbol masters, small cut, square, favicon and app icon |
| `lockups/` | Horizontal and stacked versions in five colourways |
| `wordmark/` | Wordmark in pine, white and black |
| `png/` | Ready-to-use transparent PNGs |
| `web-icons/` | Favicon, PWA icons, manifest and `<head>` snippet |
| `presentation/` | Presentation board (HTML) and slide images |

## 9. Before rollout
- **Trademark:** no clearance has been done. Run a professional search before use.
- **Name:** EXRP sits close to XRP, the cryptocurrency, so review how that plays with your buyers.
- **Mockups:** the tagline, web address, social handle and contact details on the board are placeholders.
- **Vector production:** artwork is outlined with no live fonts. The full-colour symbol uses a knob layered over the bubble, so use the one-colour files for cutting, vinyl or embroidery.
