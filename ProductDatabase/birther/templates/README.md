Manifest and Calibration XML Templates
======================================

This is the directory for the XML template fragments, combined to generate the manifest and calibration EBML.

Complete XML documents are built by starting with a "base" XML file (these have names ending in `.base.xml`), into which other XML fragments are inserted. The fragment files contain a parent element `<Fragment>`, wrapping the content that gets inserted into the base.

Both the base files and fragments contain tags, which are used to insert information about the specific device and/or calibration. These are basically Python formatting strings, like `{device.hwRev}` or `0x{birth.typeUID:08X}`, but can also contain simple expressions.

Variables available in the formatting strings for all types of fragments include:
* `birth`: The (latest) `Birth` record of the unit being birthed.
* `device`: The `Device` record of the current unit.
* `user`: The name of the user doing the birthing/calibration (i.e. the currently logged-in user's username).
* `machine`: The name of the computer being used to do the birthing/calibration.

Manifest Fragments
------------------
Most of the manifest fragments map directly to EBML elements, and bear the same names. The analog sensor fragments don't, since they are more complex.

Calibration Fragments
---------------------
There are two sets of calibration fragments: the 'default' fragments, used to create the generic calibration applied at birth, and the fragments used to populate the 'real' data after the calibration procedure. Some default fragments are used in both cases (e.g. sensors that are never individually calibrated).

Calibration-related files start with `Cal_`.

Variables available to non-default Calibration fragment formatting strings also include:
* `session`: The current `CalSession` record.
