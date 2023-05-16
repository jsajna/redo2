Calibration Certificate Templates
=================================

These SVG templates were created/edited in Inkscape. Text objects that contain fields to get filled out have IDs starting with `FIELD_` and tags in their object 'descriptions.' These description tags are in the form of Python formatting strings, e.g. `{birth.partNumber}` or `C{session.sessionId:05d}`. They may also contain expressions, like `{session.date.date()}`.

Variables available in the formatting strings include:
* `session`: The current `CalSession` record.
* `cal`: A dictionary of `CalAxis` records, keyed by calibration ID.
* `certificate`: The current `CalCertificate` record.
* `reference`: The `CalReference` (reference accelerometer) record used for calibration.
* `birth`: The (latest) `Birth` record of the device being calibrated.

The name of the template used is either explicitly given in `birth.product.calCertificate` or derived from the part number.
