"""Independent, explicitly assigned task classifications."""

from typing import Literal

Importance = Literal["unassigned", "important", "not_important"]
Urgency = Literal["unassigned", "urgent", "not_urgent"]
