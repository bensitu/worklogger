# i18n Key Mapping (Legacy -> Canonical)

## Rule
- Canonical keys are flat snake_case grouped by module prefix in source usage.
- Legacy aliases remain supported by `worklogger/utils/i18n.py` for compatibility.

## Mappings
- `theme_label` -> `theme`
- `quick_log_btn` -> `btn_quick_log`
- `regenerate` -> `btn_regenerate`
- `ai_api_key` -> `api_key`
- `ai_base_url` -> `base_url`
- `ai_model` -> `model`
- `ai_key_placeholder` -> `api_key_placeholder`
- `ai_url_placeholder` -> `base_url_placeholder`
- `ai_model_placeholder` -> `model_placeholder`
- `local_model_download_btn` -> `btn_local_model_download`
- `local_model_select_btn` -> `btn_local_model_select`
- `settings_general_show_overnight_indicator` -> `show_overnight_indicator`

## Notes
- New code should use canonical keys only.
- Alias keys are transitional and can be removed after full code replacement.
