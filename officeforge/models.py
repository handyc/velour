# OfficeForge is stateless — every request runs cc against office66.c
# with the user's chosen OFFICE_FEATURE_* flags and serves the binary
# back.  No DB tables.  This file exists so Django registers the app.
