"""Refurb: build-to-order refurbished-computer inventory workflow (InvenTree plugin).

The InvenTree/Django import is guarded because this file is an ancestor directory of
formfactor/ and tests/, which pytest's package-collection machinery touches even when
only running the pure formfactor test suite (no InvenTree server installed). Inside
the real InvenTree container this import always succeeds and RefurbPlugin is defined.
"""

PLUGIN_VERSION = "0.1.0"

try:
    from plugin import InvenTreePlugin
    from plugin.mixins import (
        AppMixin,
        EventMixin,
        ScheduleMixin,
        SettingsMixin,
        UrlsMixin,
        UserInterfaceMixin,
    )
except ImportError:
    RefurbPlugin = None
else:

    class RefurbPlugin(
        AppMixin,
        UrlsMixin,
        UserInterfaceMixin,
        ScheduleMixin,
        EventMixin,
        SettingsMixin,
        InvenTreePlugin,
    ):
        """Implements .claude/specs/workflow-spec.md: chassis intake, component stock,
        capacity reservation, build, Aiken audit and form-factor resolution, scan-time
        allocation, fulfilment, and returns.
        """

        NAME = "Refurb"
        SLUG = "refurb"
        TITLE = "Refurb Workflow"
        DESCRIPTION = "Build-to-order refurbished computer inventory workflow"
        VERSION = PLUGIN_VERSION
        AUTHOR = "Refurb Ops"

        MIN_VERSION = "1.4.0"

        SETTINGS = {}

        SCHEDULED_TASKS = {}

        def get_ui_panels(self, request, context=None, **kwargs):
            return []

        def setup_urls(self):
            return []


__all__ = ["RefurbPlugin", "PLUGIN_VERSION"]
