# Legacy Dead Code in standalone.py

The following functions, variables, and imports from the original 2025 version of `standalone.py` are preserved in the codebase to minimize the diff size and make the transition easily explainable to the team, but they are no longer executed or read in the redesigned favorite-color RL flow.

## 1. Unused Functions
* `downpressed()`: Legacy callback for down button press.
* `uppressed()`: Legacy callback for up button press.
* `selectpressed()`: Legacy callback for select button press.
* `displayselect()`: Legacy drawing callback for the icon selection screen.
* `resettohome()`: Legacy menu state reset callback.
* `check_switch()`: Legacy button polling callback registered to a hardware timer.
* `shakemotor()`: Legacy debug motor response function.
* `setloggingmode()`: Legacy function to set up logging to files.

## 2. Unused Global Variables
* `ID`: Unique hex ID of the microcontroller.
* `highlightedIcon`: List tracking active selection coordinates for legacy menus.
* `screenID`: Tracks active screen state.
* `lastPressed`, `previousIcon`, `filenumber`, `currentlocaltime`, `oldlocaltime`: Legacy menu navigation variables.
* `flags`, `playFlag`, `triggered`, `LOGGING`: Legacy state flags.

## 3. Unused Imports
* `from files import *` and `import machine, os, sys` in `standalone.py` (logging files are no longer written).
* `ubinascii` and `unique_id` (device registration is no longer used).
