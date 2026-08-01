# Web de Claridez

Aplicación React del primer flujo vertical de Claridez. Conserva autenticación y selección
organizacional e incorpora agenda, solicitudes, personas inline, cotizaciones versionadas y
confirmación o cancelación de reservas. La interfaz sigue la dirección visual oficial y responde
en escritorio y móvil.

Los componentes de marca usan los SVG oficiales de `docs/Claridez_Brand_Assets_v1.0`. Inter y Plus
Jakarta Sans se sirven desde dependencias FontSource locales fijadas por el lockfile; no dependen de
una CDN. `src/Brand.tsx` concentra el logotipo horizontal y el isotipo según el fondo.

`src/App.tsx` compone la sesión y el contexto organizacional. `src/app` contiene el espacio de
trabajo; `src/features` separa autenticación, organizaciones, agenda, solicitudes, cotizaciones y
reservas; `src/shared` contiene solo componentes, efectos y utilidades reutilizados. `src/api.ts`
permanece como el límite HTTP único. Esta arquitectura y sus pruebas de caracterización se detallan
en la [Iteración 5.1.2](../../docs/product/ITERATION_5_1_2_MAINTAINABILITY_CI.md).

## Requisitos

- Node.js 24.18.1.
- npm 11.16.0.
- Dependencias fijadas por `package.json` y el `package-lock.json` raíz.

## Instalación reproducible

Desde la raíz del repositorio:

```text
npm ci
```

Los comandos oficiales del monorepo se ejecutan también desde la raíz y están documentados en el `README.md` principal.
