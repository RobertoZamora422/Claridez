# Documentación de Claridez

Este directorio contiene las fuentes versionadas que gobiernan producto, arquitectura y marca. Los documentos cumplen funciones distintas y no deben utilizarse fuera de su ámbito.

## Índice

### Producto

- [Línea base del producto v0.1](product/PRODUCT_BASELINE.md): decisiones de producto aprobadas, alcance inicial, exclusiones y asuntos pendientes. No es una especificación funcional completa.

### Arquitectura

- [Roadmap técnico de inicialización](architecture/INITIALIZATION_ROADMAP.md): secuencia aprobada desde el gobierno documental hasta el primer flujo vertical.
- [Matriz de compatibilidad de toolchains](architecture/TOOLCHAIN_COMPATIBILITY.md): versiones exactas, dependencias, evidencia y límites de la Iteración 1.
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
