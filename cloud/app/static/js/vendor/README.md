# Vendored third-party scripts

The CSP is `script-src 'self'`, so anything the PWA loads has to live here rather
than on a CDN.

## qrcode.js

- Library: [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) v1.4.4
- License: MIT (Kazuhiko Arase)
- Source: `https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.js`, unmodified
- Used by: Settings → Android Auto device, to render the pairing QR via
  `createSvgTag()`. Inline SVG rather than `createDataURL()`, because `img-src`
  in the CSP does not allow `data:`.

To update, re-download the same file from the pinned version URL and diff it.
