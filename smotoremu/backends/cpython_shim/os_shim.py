"""Documented placeholder for future path-rewriting OS shims.

T014 currently uses the simpler design-doc-approved approach: the device thread
`chdir`s into the session VFS and wraps the specific `os` functions that need
absolute-path rejection. If parallel in-process sessions become necessary, this
module is where path-rewriting `os` shims should move.

Co-authored-by: GPT-5, Aug 2026
"""
