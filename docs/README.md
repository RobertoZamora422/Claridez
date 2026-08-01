# Documentación de Claridez

Este directorio contiene las fuentes versionadas que gobiernan producto, arquitectura y marca. Los documentos cumplen funciones distintas y no deben utilizarse fuera de su ámbito.

## Índice

### Producto

- [Línea base del producto v0.1](product/PRODUCT_BASELINE.md): decisiones de producto aprobadas, alcance inicial, exclusiones y asuntos pendientes. No es una especificación funcional completa.
- [Iteración 5.1 — De consulta a reserva confirmada](product/ITERATION_5_1_COMMERCIAL_FLOW.md): especificación implementada del primer flujo vertical.
- [Iteración 5.1.1 — Endurecimiento y cierre](product/ITERATION_5_1_1_HARDENING.md): cierre de autorización, integridad PostgreSQL, consistencia histórica e identidad visual del flujo comercial.
- [Iteración 5.1.2 — Mantenibilidad y CI](product/ITERATION_5_1_2_MAINTAINABILITY_CI.md): arquitectura interna modular, compatibilidad preservada y controles automatizados de integración.
- [Iteración 5.2 — De reserva confirmada a evento preparado](product/ITERATION_5_2_OPERATIONS_SPECIFICATION.md): especificación aprobada e implementada con validación local; el cutover del entorno destino permanece pendiente de despliegue.

### Arquitectura

- [Cutover de la Iteración 5.2](architecture/ITERATION_5_2_CUTOVER.md): procedimiento obligatorio de indisponibilidad controlada, migración atómica y postcheck previo al tráfico.

- [Roadmap técnico de inicialización](architecture/INITIALIZATION_ROADMAP.md): secuencia aprobada desde el gobierno documental hasta el primer flujo vertical.
- [Matriz de compatibilidad de toolchains](architecture/TOOLCHAIN_COMPATIBILITY.md): versiones exactas, dependencias, evidencia y límites de la Iteración 1.
- [Plataforma local y configuración](architecture/LOCAL_PLATFORM.md): PostgreSQL 17 local, variables, perfiles, privilegios, comandos y endpoints técnicos de la Iteración 2.
- [Protocolo del spike de tenancy](architecture/TENANCY_SPIKE_PROTOCOL.md): alcance, ciclo protegido y matriz experimental de la Iteración 3.
- [Resultados del spike de tenancy](architecture/TENANCY_SPIKE_RESULTS.md): evidencia histórica y benchmark que sustentaron la aceptación de ADR 0009.
- [Modelo de amenazas del spike](security/TENANCY_SPIKE_THREAT_MODEL.md): amenazas de aislamiento y controles evaluados.
- [Registro de ADR](adr/README.md): decisiones arquitectónicas, estados y plantilla.

### Marca

- [Registro de copias controladas](brand/README.md).
- [Fundamentos de marca](brand/CLARIDEZ_FUNDAMENTOS_DE_MARCA.md).
- [Dirección visual oficial](brand/CLARIDEZ_DIRECCION_VISUAL_OFICIAL.md).

## Jerarquía por ámbito

No existe una única fuente que reemplace a todas las demás:

- Los fundamentos de marca son la fuente principal para propósito, posicionamiento, personalidad y lenguaje.
- La dirección visual oficial prevalece exclusivamente para decisiones visuales.
- La línea base del producto registra decisiones de alcance aprobadas sin definir procesos ni reglas funcionales completas.
- Los ADR aceptados gobiernan las decisiones arquitectónicas específicas que documentan.
- Las futuras especificaciones funcionales gobernarán únicamente los flujos para los que hayan sido aprobadas.

Una contradicción aparente debe resolverse atendiendo primero al ámbito de cada documento. Si el ámbito no permite resolverla, se debe registrar la decisión antes de implementar.

## Estados documentales

- **Aceptado:** decisión aprobada y vigente.
- **Provisional:** dirección de trabajo aprobada temporalmente, sujeta a definición posterior.
- **Diferido:** asunto deliberadamente postergado hasta que exista una necesidad o iteración autorizada.
- **Requiere spike:** hipótesis que debe comprobarse técnicamente antes de adoptarse.

## Reglas de mantenimiento

- Usar español, UTF-8 y LF.
- Preferir enlaces relativos.
- No incorporar rutas absolutas de equipos personales.
- Actualizar este índice al añadir una nueva fuente de verdad.
- No modificar silenciosamente las copias controladas de marca.
- Registrar mediante ADR las decisiones arquitectónicas difíciles de revertir.
