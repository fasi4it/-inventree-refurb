from django.db import models

from part.models import Part
from stock.models import StockItem


class RefurbModel(models.Model):
    """Base class for refurb plugin models.

    InvenTree denies all access to a plugin model that omits check_user_permission —
    it does not fall back to a default. Every subclass gets a safe default here so that
    omission can't happen by accident; tighten per-model where roles actually differ.
    """

    class Meta:
        abstract = True

    @classmethod
    def check_user_permission(cls, user, permission) -> bool:
        return bool(user and user.is_authenticated)


class FormFactor(models.TextChoices):
    TINY = "TINY", "Tiny"
    USFF = "USFF", "USFF"
    SFF = "SFF", "SFF"
    TOWER = "TOWER", "Tower"
    LAPTOP = "LAPTOP", "Laptop"


class ChassisModel(RefurbModel):
    """Side table on a chassis-model Part: the part-number lookup table that replaces
    the "processor ends in T" rule (workflow-spec.md §12.1).
    """

    part = models.OneToOneField(
        Part, on_delete=models.CASCADE, related_name="refurb_chassis_model"
    )
    part_number = models.CharField(max_length=64, unique=True, db_index=True)
    manufacturer = models.CharField(max_length=32)
    model_name = models.CharField(max_length=128)
    form_factor = models.CharField(
        max_length=16, choices=FormFactor.choices, null=True, blank=True
    )
    ambiguous = models.BooleanField(default=False)
    ram_slots = models.PositiveSmallIntegerField(null=True, blank=True)
    max_ram_gb = models.PositiveIntegerField(null=True, blank=True)
    supports_optical = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.CharField(max_length=128, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(ambiguous=True) | models.Q(form_factor__isnull=False),
                name="refurb_chassismodel_ambiguous_or_resolved",
            )
        ]

    def __str__(self) -> str:
        return f"{self.part_number} ({self.model_name})"


class ChassisStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    AWAITING_AUDIT = "AWAITING_AUDIT", "Awaiting audit"
    REVIEW_QUEUE = "REVIEW_QUEUE", "Review queue"
    AVAILABLE = "AVAILABLE", "Available"
    ALLOCATED = "ALLOCATED", "Allocated"
    SHIPPED = "SHIPPED", "Shipped"
    RETURNED = "RETURNED", "Returned"
    SCRAP = "SCRAP", "Scrap"


class ChassisState(RefurbModel):
    """Side table on a serialised chassis StockItem: the refurb lifecycle (spec §2.1).

    Only AVAILABLE counts toward saleable stock. REVIEW_QUEUE is deliberately excluded
    from availability so an unresolved unit can never be sold.
    """

    stock_item = models.OneToOneField(
        StockItem, on_delete=models.CASCADE, related_name="refurb_chassis_state"
    )
    status = models.CharField(
        max_length=16, choices=ChassisStatus.choices, default=ChassisStatus.RECEIVED
    )
    form_factor = models.CharField(
        max_length=16, choices=FormFactor.choices, null=True, blank=True
    )
    form_factor_source = models.CharField(max_length=32, blank=True)
    grade = models.CharField(max_length=1, blank=True)
    cost_basis = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    has_os = models.BooleanField(default=False)
    os_licence = models.CharField(max_length=128, blank=True)
    field_modified = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "form_factor"])]

    def __str__(self) -> str:
        return f"{self.stock_item.serial} [{self.status}]"
