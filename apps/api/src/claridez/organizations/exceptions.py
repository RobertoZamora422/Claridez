"""Errores de dominio de organizaciones y membresías."""


class OrganizationDomainError(Exception):
    """Base para errores esperados del dominio organizacional."""


class OrganizationNotFound(OrganizationDomainError):
    pass


class MembershipNotFound(OrganizationDomainError):
    pass


class OrganizationSlugConflict(OrganizationDomainError):
    pass


class MembershipAlreadyExists(OrganizationDomainError):
    pass


class UserNotActive(OrganizationDomainError):
    pass


class InvalidOrganizationTransition(OrganizationDomainError):
    pass


class InvalidMembershipTransition(OrganizationDomainError):
    pass


class InvalidMembershipRoleChange(OrganizationDomainError):
    pass


class LastActiveOwnerRequired(OrganizationDomainError):
    pass


class BootstrapConflict(OrganizationDomainError):
    pass


class AuthorizationDenied(OrganizationDomainError):
    """Denegación cerrada sin detalles sensibles."""


class UnknownCapability(AuthorizationDenied):
    pass


class UnknownMembershipRole(AuthorizationDenied):
    pass


class TenantAccessDenied(AuthorizationDenied):
    pass


class ConflictingTenantScope(AuthorizationDenied):
    pass
