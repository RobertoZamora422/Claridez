# Claridez — Línea base del producto v0.1

- **Versión:** 0.1
- **Estado:** Línea base aprobada para iniciar el producto
- **Mercado inicial:** Ecuador
- **Fecha:** 31 de julio de 2026

## Naturaleza de este documento

Este documento registra las decisiones de producto aprobadas hasta la Iteración 0. **No es una especificación funcional completa** y no define de forma definitiva procesos, entidades, estados, cálculos, permisos, pantallas ni reglas de negocio.

Cada flujo funcional deberá contar con una especificación separada antes de implementarse. Si una futura especificación necesita cambiar esta línea base, el cambio deberá revisarse y versionarse explícitamente.

## Identidad y propósito

El producto se llama **Claridez** y es una plataforma SaaS B2B multiempresa especializada inicialmente en la gestión integral de salones y espacios de eventos.

Su propósito es ayudar a propietarios y administradores a construir negocios organizados, controlados y rentables. La promesa de marca es:

> Todo tu negocio, claro y bajo control.

Claridez es completamente independiente de RFM Core. No reutilizará su código, migraciones, estructura interna, historial ni configuración.

## Dirección inicial del producto

La visión contempla centralizar progresivamente información comercial, disponibilidad, contratación, pagos, preparación operativa, costos, gastos y rentabilidad. Esta enumeración expresa áreas del problema, no módulos, entidades o flujos definitivos.

Claridez debe priorizar:

- Seguridad e integridad de datos.
- Aislamiento entre organizaciones.
- Claridad de la información.
- Mantenibilidad.
- Reglas de negocio verificadas.
- Utilidad especializada para el mercado inicial.

Más funcionalidades no implican automáticamente una mejor arquitectura ni un mejor producto.

## Mercado, moneda y tiempo

- País inicial: Ecuador.
- Zona horaria inicial: `America/Guayaquil`.
- Moneda inicial: USD.
- Moneda y zona horaria deberán modelarse como configuración de cada organización.

Las reglas de impuestos, redondeo, formatos, fechas de corte y localización requieren especificación posterior.

## Fundamentos multiempresa

- El producto será multiempresa desde el inicio.
- Una organización representa el límite principal de aislamiento de datos privados.
- Todo dato privado deberá pertenecer a una organización.
- Un usuario podrá pertenecer a varias organizaciones mediante membresías.
- La estrategia técnica de aislamiento fue aceptada después del spike en ADR 0009: aplicación
  tenant-aware más PostgreSQL RLS como defensa en profundidad.

Este documento no define todavía el ciclo de vida de organizaciones, membresías, invitaciones o cambios de contexto.

## Perfiles iniciales provisionales

Los nombres y propósitos generales aprobados son:

- `propietario`: referente principal de la organización y de su control general.
- `administrador`: apoyo en la administración cotidiana de la organización.
- `comercial`: trabajo relacionado con la gestión comercial.
- `operaciones`: trabajo relacionado con la preparación y ejecución operativa.
- `finanzas`: trabajo relacionado con el seguimiento económico y financiero.

Los perfiles son provisionales. ADR 0011 aprueba una matriz limitada a la infraestructura de la
Iteración 4; no constituye el contrato definitivo de permisos, capacidades, precedencias o
excepciones de módulos futuros.

## Arquitectura de producto aprobada

- Repositorio privado, propietario y organizado como monorepo.
- Monolito modular.
- Django y Django REST Framework para backend.
- React, TypeScript estricto y Vite para frontend.
- PostgreSQL en todos los ambientes.
- API REST JSON versionada mediante `/api/v1`.
- Contrato OpenAPI y futuro cliente TypeScript generado.
- No se utilizarán microservicios.

Las versiones exactas y librerías auxiliares requieren una matriz de compatibilidad en la Iteración 1.

## Exclusiones de V1 aprobadas

- Contabilidad formal.
- Facturación electrónica.
- Constructor web libre.

El Modelo de Conversión, la página pública y los dominios propios pertenecen a la visión y a un plan superior, pero no serán el primer flujo funcional.

## Asuntos deliberadamente abiertos

- Primer flujo vertical funcional.
- Procesos y estados de cada área.
- Matriz definitiva de autorización.
- Proveedor OIDC futuro, sin alterar la identidad local desacoplada aceptada en ADR 0010.
- Reglas financieras y de disponibilidad.
- Política de retención, exportación y eliminación.
- Infraestructura y proveedores de staging y producción.
- Planes comerciales y capacidades por plan.
- Requisitos detallados del Modelo de Conversión.

Ninguno de estos asuntos debe resolverse implícitamente dentro de código de infraestructura o componentes visuales.

## Fuentes de marca

Los fundamentos de marca gobiernan propósito, posicionamiento, personalidad y lenguaje. La dirección visual oficial prevalece exclusivamente en decisiones visuales. La jerarquía completa se documenta en [docs/brand/README.md](../brand/README.md).
