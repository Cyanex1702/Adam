; App binaries must never be installed over ADAM's existing owner store/assets.
!macro NSIS_HOOK_PREINSTALL
  StrCmp "$INSTDIR" "$LOCALAPPDATA\ADAM" adam_data_directory_denied
  IfFileExists "$INSTDIR\runtime.sqlite3" adam_data_directory_denied
  IfFileExists "$INSTDIR\security\auth.sqlite3" adam_data_directory_denied
  Goto adam_data_directory_safe
  adam_data_directory_denied:
    MessageBox MB_OK|MB_ICONSTOP "Choose a separate application folder. This folder contains ADAM data or model assets." /SD IDOK
    SetErrorLevel 2
    Abort
  adam_data_directory_safe:
!macroend
