from __future__ import annotations

import uuid
from typing import Any

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Trim

from claridez.organizations.models import Membership, Organization

from .normalization import canonical_optional_text, canonical_text


class TenantCatalogModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, db_index=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class EventType(TenantCatalogModel):
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="catalog_eventtype_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "name"], name="catalog_eventtype_org_name_uq"
            ),
            models.CheckConstraint(
                condition=Q(name=Trim("name")) & ~Q(name=""),
                name="catalog_eventtype_name_canonical",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="catalog_eventtype_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.name = canonical_text(self.name, field="El tipo de evento", max_length=100)
        super().save(*args, **kwargs)


class EventTypeRevision(TenantCatalogModel):
    event_type = models.ForeignKey(
        EventType, on_delete=models.PROTECT, related_name="revisions", db_index=False
    )
    revision = models.PositiveIntegerField()
    name = models.CharField(max_length=100)
    is_active = models.BooleanField()
    changed_by_membership = models.ForeignKey(Membership, on_delete=models.PROTECT, db_index=False)

    class Meta:
        ordering = ["event_type_id", "revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="catalog_eventtyperevision_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "event_type", "revision"],
                name="catalog_eventtyperevision_org_type_rev_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="catalog_eventtyperevision_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type_id}@{self.revision}"


class CatalogItem(TenantCatalogModel):
    class Kind(models.TextChoices):
        SERVICE = "service", "Servicio"
        PRODUCT = "product", "Producto"
        PACKAGE = "package", "Paquete"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=150)
    description = models.CharField(max_length=500, blank=True)
    unit_label = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="catalog_item_org_id_uq"),
            models.UniqueConstraint(
                fields=["organization", "kind", "name"], name="catalog_item_org_kind_name_uq"
            ),
            models.CheckConstraint(
                condition=Q(kind__in=["service", "product", "package"]),
                name="catalog_item_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(name=Trim("name")) & ~Q(name=""), name="catalog_item_name_canonical"
            ),
            models.CheckConstraint(
                condition=Q(unit_label=Trim("unit_label")) & ~Q(unit_label=""),
                name="catalog_item_unit_canonical",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="catalog_item_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.name = canonical_text(self.name, field="El nombre del catálogo", max_length=150)
        self.description = canonical_optional_text(
            self.description, field="La descripción", max_length=500
        )
        self.unit_label = canonical_text(self.unit_label, field="La unidad", max_length=40)
        super().save(*args, **kwargs)


class CatalogItemRevision(TenantCatalogModel):
    item = models.ForeignKey(
        CatalogItem, on_delete=models.PROTECT, related_name="revisions", db_index=False
    )
    revision = models.PositiveIntegerField()
    kind = models.CharField(max_length=16, choices=CatalogItem.Kind.choices)
    name = models.CharField(max_length=150)
    description = models.CharField(max_length=500, blank=True)
    unit_label = models.CharField(max_length=40)
    is_active = models.BooleanField()
    package_components = models.JSONField(default=list)
    changed_by_membership = models.ForeignKey(Membership, on_delete=models.PROTECT, db_index=False)

    class Meta:
        ordering = ["item_id", "revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="catalog_itemrevision_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "item", "revision"],
                name="catalog_itemrevision_org_item_rev_uq",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="catalog_itemrevision_revision_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item_id}@{self.revision}"


class PackageComponent(TenantCatalogModel):
    package = models.ForeignKey(
        CatalogItem, on_delete=models.PROTECT, related_name="package_components", db_index=False
    )
    package_revision = models.PositiveIntegerField()
    component = models.ForeignKey(
        CatalogItem, on_delete=models.PROTECT, related_name="included_in_packages", db_index=False
    )
    component_revision = models.ForeignKey(
        CatalogItemRevision,
        on_delete=models.PROTECT,
        related_name="package_component_uses",
        db_index=False,
    )
    position = models.PositiveIntegerField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"], name="catalog_component_org_id_uq"
            ),
            models.UniqueConstraint(
                fields=["organization", "package", "package_revision", "position"],
                name="catalog_component_org_package_position_uq",
            ),
            models.UniqueConstraint(
                fields=["organization", "package", "package_revision", "component"],
                name="catalog_component_org_package_item_uq",
            ),
            models.CheckConstraint(
                condition=Q(package_revision__gte=1) & Q(position__gte=1) & Q(quantity__gt=0),
                name="catalog_component_values_valid",
            ),
            models.CheckConstraint(
                condition=~Q(package=F("component")), name="catalog_component_not_self"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.package_id}@{self.package_revision}:{self.position}"


class CatalogPrice(TenantCatalogModel):
    item = models.ForeignKey(
        CatalogItem, on_delete=models.PROTECT, related_name="prices", db_index=False
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    validity = DateTimeRangeField()
    revision = models.PositiveIntegerField(default=1)
    created_by_membership = models.ForeignKey(Membership, on_delete=models.PROTECT, db_index=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["item_id", "validity", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "id"], name="catalog_price_org_id_uq"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="catalog_price_amount_valid"),
            models.CheckConstraint(condition=Q(currency="USD"), name="catalog_price_currency_usd"),
            models.CheckConstraint(
                condition=Q(revision__gte=1), name="catalog_price_revision_positive"
            ),
            ExclusionConstraint(
                name="catalog_price_no_overlap",
                expressions=[
                    ("organization", RangeOperators.EQUAL),
                    ("item", RangeOperators.EQUAL),
                    ("validity", RangeOperators.OVERLAPS),
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item_id}@{self.amount} {self.currency}"
