# Documentación de Claridez

Este directorio contiene las fuentes versionadas que gobiernan producto, arquitectura, seguridad y
marca. Cada documento se interpreta dentro de su ámbito.

## Fuentes centrales

- [Blueprint maestro del producto funcional](product/PRODUCT_BLUEPRINT.md): destino completo,
  módulos, experiencia, límites y definición verificable de terminado.
- [Roadmap completo de entrega](product/PRODUCT_DELIVERY_ROADMAP.md): historia, estado real, etapas
  pendientes, dependencias y siguiente etapa.
- [Handoff del proyecto](PROJECT_HANDOFF.md): continuidad operativa para una cuenta o agente sin
  memoria previa.

Estas tres fuentes se leen juntas. El Blueprint responde «qué producto debe quedar», el Roadmap
«en qué orden y estado se entrega» y el Handoff «desde qué checkout y reglas se continúa».

## Producto

- [Línea base del producto v0.1](product/PRODUCT_BASELINE.md): antecedente aprobado de la
  inicialización; no es la definición completa vigente.
- [Iteración 5.1 — De consulta a reserva confirmada](product/ITERATION_5_1_COMMERCIAL_FLOW.md):
  contrato implementado del flujo comercial inicial.
- [Iteración 5.1.1 — Endurecimiento](product/ITERATION_5_1_1_HARDENING.md): cierre de autorización,
  integridad y privacidad comercial.
- [Iteración 5.1.2 — Mantenibilidad y CI](product/ITERATION_5_1_2_MAINTAINABILITY_CI.md): límites
  internos, compatibilidad y controles automatizados.
- [Iteración 5.2 — De reserva confirmada a evento preparado](product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md):
  contrato operativo implementado y validado localmente.

## Arquitectura y seguridad

- [Registro de ADR](adr/README.md): decisiones arquitectónicas aceptadas y plantilla.
- [Plataforma local](architecture/LOCAL_PLATFORM.md): PostgreSQL, variables, perfiles, privilegios y
  comandos.
- [Toolchains](architecture/TOOLCHAIN_COMPATIBILITY.md): versiones y evidencia reproducible.
- [Cutover 5.2](architecture/ITERATION_5_2_CUTOVER.md): procedimiento obligatorio antes de tráfico
  en un entorno destino.
- [Roadmap técnico de inicialización](architecture/INITIALIZATION_ROADMAP.md): documento histórico
  limitado a I0–I5; no gobierna entregas futuras.
- [Protocolo](architecture/TENANCY_SPIKE_PROTOCOL.md),
  [resultados](architecture/TENANCY_SPIKE_RESULTS.md) y
  [modelo de amenazas](security/TENANCY_SPIKE_THREAT_MODEL.md) del spike: evidencia histórica; su
  código fue eliminado.

## Marca

- [Registro de copias controladas](brand/README.md).
- [Fundamentos de marca](brand/CLARIDEZ_FUNDAMENTOS_DE_MARCA.md).
- [Dirección visual oficial](brand/CLARIDEZ_DIRECCION_VISUAL_OFICIAL.md).
- `Claridez_Brand_Assets_v1.0`: recursos oficiales versionados.

## Precedencia por ámbito

1. `AGENTS.md` define reglas operativas obligatorias.
2. Los ADR aceptados gobiernan su decisión arquitectónica.
3. El Blueprint gobierna el destino y los límites del producto.
4. Una especificación funcional aprobada gobierna el flujo exacto que describe.
5. El Roadmap gobierna estado y secuencia; el Handoff resume el punto observado.
6. La línea base v0.1 y el roadmap de inicialización son antecedentes históricos.
7. Fundamentos de marca gobiernan propósito, posicionamiento, personalidad y lenguaje.
8. Dirección Visual prevalece exclusivamente en decisiones visuales.

Una contradicción fuera de esos ámbitos debe documentarse y resolverse antes de implementar la
decisión afectada.

## Mantenimiento

- Usar español, UTF-8 sin BOM y LF.
- Preferir enlaces relativos y comprobar su existencia.
- No incorporar rutas absolutas personales, secretos ni datos reales.
- Actualizar este índice al añadir una fuente de verdad.
- No editar silenciosamente copias controladas de marca.
- Actualizar Roadmap y Handoff al cerrar cada etapa; cambiar el Blueprint solo si cambia el destino
  aprobado del producto.
- Reservar ADR para decisiones transversales o difíciles de revertir; no exigir documentación
  extensa para decisiones locales y reversibles.
