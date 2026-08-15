# Capataz — Design System

Fuente de verdad extraída del código real (`src/styles/app.scss`, componentes Vue y páginas)
el 2026-08-14. Este documento describe el sistema **tal y como existe hoy**, no un objetivo
aspiracional. Si algo cambia en `app.scss` o en los componentes, actualiza este documento junto
con el cambio.

Ver también: `design-system.html` en esta misma carpeta — guía de estilos viva, navegable en el
navegador, con conmutador claro/oscuro real.

## 1. Qué es Capataz y cómo informa esto al diseño

Capataz es una consola privada para **ver y operar de forma controlada** los servicios Docker
de un homelab: no es una terminal ni un panel de administración genérico. Esto se traduce en
decisiones de diseño consistentes en todo el frontend:

- **Densidad de información sobre ornamento.** Rejillas de tarjetas, tablas, paneles de datos.
  Sin ilustraciones, sin gradientes decorativos, sin sombras pronunciadas.
- **El color comunica estado, no marca.** El teal de marca (`--color-primary` /
  `--color-accent-text`) se reserva para navegación, enlaces y foco; el verde/rojo/ámbar
  siempre significa healthy/error/en-progreso, nunca decoración. El naranja de marca
  (`--color-brand`) está aún más restringido: solo aparece en el logo/favicon, en ningún
  otro elemento de interfaz — ver §7.1.
- **Todo tiene borde, nada flota.** Tarjetas y paneles usan `border: 1px solid var(--color-border)`
  en vez de `box-shadow`. Encaja con el tono "panel de control", no "app de consumo".
  la superficie tiene su radio propio (`--radius-md`/`--radius-lg`), pero no elevación.
  fields.
- **Oscuro por defecto.** El modo oscuro es el estado inicial (`Dark.set(... !== 'light')`);
  el modo claro es la variante, no al revés.
- **Acciones peligrosas se ven peligrosas.** Todo lo `critical` fuerza un diálogo con icono
  `warning` en rojo (`color="negative"`) y un campo de motivo obligatorio — ver §8.7.

## 2. Color

### 2.1 Tokens de marca (CSS custom properties)

Definidos en `src/styles/app.scss`. El tema oscuro vive en `:root`; el tema claro sobrescribe
esas mismas variables bajo el selector `body.body--light` (Quasar's `Dark` plugin siempre
estampa `body--dark` o `body--light` en `<body>`, nunca ninguno de los dos — ver §7).

| Token | Oscuro (por defecto) | Claro (`body.body--light`) | Uso |
|---|---|---|---|
| `--color-bg` | `#101618` | `#f4f6f6` | Fondo de página, fondo de bloques de código/log |
| `--color-surface` | `#182023` | `#ffffff` | Tarjetas, paneles, header, drawer, auth-card |
| `--color-surface-2` | `#1d282c` | `#eef1f1` | Superficie secundaria (declarada; uso puntual) |
| `--color-border` | `#344245` | `#d7dfe0` | Bordes de tarjeta/panel/tabla/inputs |
| `--color-text` | `#e7eceb` | `#16211f` | Texto principal |
| `--color-text-muted` | `#aab7b8` | `#55676a` | Texto secundario, labels, metadatos, timestamps |
| `--color-primary` | `#64aab0` | `#2f7d84` | Foco (`:focus-visible`), teal de marca. **No** es el azul de los botones Quasar — ver §2.3 |
| `--color-error` | `#e18080` | `#b3261e` | Declarado para texto de error (uso puntual; el banner de error tiene su propio par fg/bg — ver §8.8) |
| `--color-success` | `#8ac47d` | `#1f6b3a` | Declarado para éxito (uso puntual — ver `.success-banner` §8.8) |
| `--color-accent-text` | `#a8dce0` | `#0f6b73` | Eyebrows, enlaces (`.q-table a`, `code`), nav activo, iconos superiores de tarjeta |
| `--color-brand` | `#ff6600` | `#ff6600` (sin override) | Logo del header y favicon — "naranja de casco de obra". Único token que **no** se retema bajo `body.body--light`: el logo mantiene su color de identidad en ambos temas — ver §7 |

Notas de implementación:

- Los valores claros y oscuros de `--color-accent-text` **no** son el mismo tono aclarado/oscurecido
  al azar: el claro está deliberadamente oscurecido (`#0f6b73` en vez de un teal pálido) para
  mantener el contraste de texto sobre un fondo casi blanco — comentario explícito en el código.
- `--color-primary` (teal de marca) es un token **distinto** del color `primary` de Quasar
  (azul `#1976D2`, por defecto del framework — nunca se sobrescribió en `quasar.config.ts`).
  Conviven dos "primarios": el teal para foco/nav/acentos de texto, y el azul de Quasar para
  botones de acción y el badge de estado `running`. Es el estado real del código, no un error de
  transcripción — cualquier trabajo de rediseño debería decidir explícitamente si unificarlos.

### 2.2 Paleta semántica de Quasar (sin modificar)

`quasar.config.ts` no define variables SCSS de marca, así que todo prop `color="..."` de Quasar
(`q-badge`, `q-btn`, `q-icon`) usa la paleta por defecto del framework:

| Nombre Quasar | Hex | Dónde aparece |
|---|---|---|
| `primary` | `#1976D2` | Botones "Ejecutar", badge de ejecución `running` |
| `positive` | `#21BA45` | Badge de servicio `healthy`, badge de ejecución `succeeded`/`Correcta` |
| `negative` | `#C10015` | Badge de servicio `down`, badge de ejecución `failed`/`rejected`, icono de diálogo crítico, botón "Ejecutar acción crítica", iconos de borrar en Catálogo |
| `warning` | `#F2C037` | Badge de servicio `degraded`, badge de ejecución `timed_out` |
| `info` | `#31CCEC` | Badge de servicio `maintenance` |
| `grey-7` | `#616161` | Badge de servicio `unknown`, badge de ejecución `queued`/`cancelled` |

Estos colores **no** se tocan por el tema claro/oscuro — Quasar los mantiene fijos; solo cambia
el fondo/texto circundante.

### 2.3 Reglas de uso

- Nunca introducir un color hexadecimal suelto en un componente: usa una variable `--color-*`
  existente o un `color` semántico de Quasar. Si ninguno encaja, añade el token a `app.scss`,
  no lo hardcodees.
- El contraste del `.error-banner` está calculado explícitamente para superar 4.5:1 por sí solo
  (no solo mezclado con un fondo concreto) — ver el comentario en `app.scss:318`. Si tocas ese
  color, vuelve a comprobar el contraste en ambos temas.

## 3. Tipografía

| Token | Valor | Uso |
|---|---|---|
| `--font-display` | `'General Sans', 'Segoe UI', sans-serif` | `h1`, títulos de tarjeta/panel (`h2`), marca en el header |
| `--font-body` | `'Satoshi', 'Segoe UI', sans-serif` | Todo lo demás (`body`) |
| monospace | `'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace` | `.event-log` (salida de ejecución) |

Ambas familias se cargan desde Fontshare (`index.html`):
`https://api.fontshare.com/v2/css?f[]=general-sans@500,600,700&f[]=satoshi@400,500,700`.
Pesos disponibles: General Sans 500/600/700, Satoshi 400/500/700. No cargar otros pesos sin
actualizar ese enlace.

### 3.1 Escala tipográfica (fluida, `clamp()`)

| Token | `clamp()` | Uso típico |
|---|---|---|
| `--text-xs` | `clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem)` | Eyebrows, labels de tabla/lista, drawer-title, timestamps |
| `--text-sm` | `clamp(0.875rem, 0.8rem + 0.35vw, 1rem)` | Descripciones de tarjeta, `panel-intro`, `detail-list dd` |
| `--text-base` | `clamp(1rem, 0.95rem + 0.25vw, 1.125rem)` | Cuerpo (`body`) |
| `--text-lg` | `clamp(1.125rem, 1rem + 0.75vw, 1.5rem)` | `h2` de tarjeta/panel |
| `--text-xl` | `clamp(1.5rem, 1.2rem + 1.25vw, 2.25rem)` | `h1` de página |

Todos escalan con el viewport — no hay saltos por media query para tipografía, solo para layout
(§5.2).

### 3.2 Tratamiento de titulares

- `h1` de página: `font-family: var(--font-display)`, `font-weight: 650`,
  `letter-spacing: -0.04em`.
- Eyebrow (kicker sobre el `h1`, p. ej. "CONTROL PLANE", "ADMINISTRACIÓN", "TRAZABILIDAD"):
  `color: var(--color-accent-text)`, `font-size: var(--text-xs)`, `font-weight: 700`,
  `letter-spacing: 0.14em`, siempre en mayúsculas en el contenido (no forzado por CSS
  `text-transform`, así que el texto fuente ya viene en mayúsculas).
  Título del drawer (`drawer-title`, p. ej. "OPERACIÓN"): mismo patrón pero `letter-spacing: 0.13em`.
- `h2` (tarjeta/panel): `font-family: var(--font-display)`, `letter-spacing: -0.02em`, sin
  cambio de peso explícito (hereda el normal/700 según el navegador para `<h2>`).

## 4. Espaciado

Escala de 8 pasos en `rem`, expuesta como variables `--space-N` (N ≈ tamaño en unidades de 4px):

| Token | Valor |
|---|---|
| `--space-1` | `0.25rem` (4px) |
| `--space-2` | `0.5rem` (8px) |
| `--space-3` | `0.75rem` (12px) |
| `--space-4` | `1rem` (16px) |
| `--space-5` | `1.25rem` (20px) |
| `--space-6` | `1.5rem` (24px) |
| `--space-8` | `2rem` (32px) |
| `--space-10` | `2.5rem` (40px) |
| `--space-12` | `3rem` (48px) |

Regla práctica observada en el código: gaps internos de componente pequeño usan `--space-1`/`-2`;
padding de tarjeta/panel usa `--space-4`–`--space-5`; separación entre secciones de página usa
`--space-6`–`--space-8`; el padding exterior de `.page` es fluido:
`clamp(var(--space-6), 4vw, var(--space-12))`.

## 5. Radios y bordes

| Token | Valor | Uso |
|---|---|---|
| `--radius-sm` | `0.375rem` (6px) | `.nav-active`, banners de auth-card |
| `--radius-md` | `0.5rem` (8px) | Tarjetas de servicio, paneles, `.event-log`, skeletons |
| `--radius-lg` | `0.75rem` (12px) | `.auth-card` |

No hay `box-shadow` en ningún componente propio del proyecto (`grep` en `app.scss` no devuelve
ninguna sombra). La separación visual viene siempre de `border: 1px solid var(--color-border)`
sobre `--color-surface`, nunca de elevación. Mantén esta convención: si un componente nuevo
necesita "destacar", dale borde/fondo, no sombra.

### 5.1 Layout de página

- `.page`: `max-width: 1440px`, centrado, padding fluido (ver arriba).
- `.page-header` / `.detail-header`: flex con `justify-content: space-between`, colapsa a
  columna por debajo de 700px.
- Rejillas: `.services-grid` (`repeat(auto-fill, minmax(280px, 1fr))`), `.filters`
  (3 columnas asimétricas `2fr 1fr 1fr`), `.detail-grid` / `.execution-grid` / `.catalog-grid`
  (2 columnas iguales) — todas colapsan a 1 columna por debajo de 700px.

### 5.2 Breakpoint

Un único breakpoint propio: `@media (max-width: 700px)`. Por debajo, todas las rejillas pasan a
una columna, `.page` reduce su padding a `--space-5`, y los botones de cabecera de página pasan a
`width: 100%`. No hay breakpoints intermedios definidos en CSS propio (Quasar aporta los suyos
para su grid interno, pero el proyecto no los usa directamente).

## 6. Tema oscuro / claro — mecanismo

1. Quasar `Dark` plugin controla el modo; estampa **siempre** `body--dark` o `body--light` en
   `<body>` (nunca ninguno de los dos).
2. `AppLayout.vue` fija el modo en cada `onMounted` (se re-ejecuta en cada navegación porque no
   hay una instancia de layout persistente entre rutas) leyendo `localStorage['capataz.theme']`;
   por defecto es oscuro (`Dark.set(localStorage.getItem(KEY) !== 'light')`).
3. El botón de alternancia (icono `light_mode`/`dark_mode` en el header) llama a `Dark.toggle()`
   y persiste la elección en ese mismo `localStorage` key.
4. Todo el retema es CSS puro: las variables `--color-*` se redefinen bajo `body.body--light`;
   ningún componente Vue tiene lógica condicional de color explícita más allá de leer esas
   variables o (para `q-badge`/`q-btn`) usar los nombres semánticos fijos de Quasar (§2.2), que
   no cambian entre temas.
5. `<meta name="theme-color" content="#151b1e">` en `index.html` está fijado al oscuro y no se
   actualiza dinámicamente con el toggle — fuera del alcance de este documento, pero queda
   anotado por si se aborda accesibilidad de barra de navegador móvil.

## 7. Iconografía

Material Icons (`extras: ['material-icons']` en `quasar.config.ts`), usados vía `q-icon`/prop
`icon` de `q-btn`. Nombres observados en el código (no exhaustivo, pero cubre todos los patrones
recurrentes):

- Navegación: `grid_view` (Servicios), `receipt_long` (Ejecuciones), `inventory_2` (Catálogo),
  `policy` (Auditoría), `menu` (plegar/desplegar el drawer, visible en cualquier ancho de pantalla).
- Cabecera: `light_mode`/`dark_mode` (toggle tema), `language` (selector de idioma),
  `account_circle` (menú de cuenta), `logout`, `verified_user` (chip de usuario en el pie del
  drawer), `radio_button_checked`/`radio_button_unchecked` (selector de rol en `dev_mock` y
  selector de idioma).
- Estado de servicio (`ServiceStatusBadge.vue`): `check_circle` (healthy), `warning` (degraded),
  `cancel` (down), `build` (maintenance), `help` (unknown).
- Acciones de tarjeta/detalle: icono declarado por la propia `ActionDefinition`
  (`action.icon ?? 'play_arrow'`); patrones vistos: `play_arrow` (iniciar), `stop` (detener),
  `restart_alt`/`autorenew`-like (reiniciar, representado como icono de refresco), `article`/
  `receipt_long`-like (logs). El icono es dato de catálogo, no hardcode de componente — no asumas
  un icono fijo por tipo de acción sin mirar el catálogo real.
- Diálogo crítico: `warning` en rojo (`color="negative"`, 28px).
- Icono por defecto de tarjeta de servicio cuando el catálogo no define uno: `dns`.

### 7.1 Logotipo de marca

El logo (`.brand svg`, header, 32×32 renderizado) es un `<svg viewBox="0 0 64 64">` inline: un
búho geométrico visto de frente — silueta con dos penachos cortos, dos grandes discos oculares
"en negativo" (blancos) con pupila central y pico romboidal también blanco. A diferencia del
resto de la iconografía (Material Icons, `currentColor`), el búho **no** hereda el color del
texto: cada `fill` está anclado a `var(--color-brand)` (los discos/pico siempre en blanco puro),
así que se ve igual —naranja— en ambos temas. Fuente vectorial original en
`design-system/capataz-logo.icon.svg`; la versión de producción está inlined en
`src/layouts/AppLayout.vue`.

### 7.2 Favicon

Generado a partir del mismo SVG del búho, con el naranja de marca hardcodeado (`#ff6600`, no
puede resolver `var(--color-brand)` fuera del DOM de la app):

| Archivo | Uso | Cómo se generó |
|---|---|---|
| `public/favicon.svg` | `<link rel="icon" type="image/svg+xml">` — favicon principal en navegadores modernos | Copia del vector con `fill` fijado a `#ff6600` |
| `public/favicon-32.png` | `<link rel="alternate icon">` — fallback raster | `convert -background none -density 384 favicon.svg -resize 32x32` |
| `public/apple-touch-icon.png` | `<link rel="apple-touch-icon">` — iconos iOS/Android al añadir a pantalla de inicio | Mismo comando, `-resize 180x180` |

Si el búho o el naranja de marca cambian, hay que regenerar los tres archivos y volver a
sincronizar el hex a mano — no hay una única fuente de verdad automática entre
`--color-brand` (CSS) y estos SVG/PNG estáticos.

## 8. Inventario de componentes

Cada entrada indica el archivo fuente para no duplicar lógica al modificar.

### 8.1 Header (`layouts/AppLayout.vue`, clase `.header`)

`q-header bordered`, fondo `--color-surface`, texto `--color-text` (override explícito porque
`QHeader` trae un blanco fijo por defecto que solo "coincide por casualidad" con el tema oscuro
— comentario en el código). Contiene: botón de menú (visible en todos los anchos, plegar/desplegar
el drawer), marca+logo, spacer, toggle de tema, selector de idioma (`LanguageSelector.vue`, entre
el toggle de tema y el menú de cuenta), menú de cuenta.

### 8.2 Drawer / navegación (`.drawer`, `.drawer-title`, `.nav-active`, `.drawer-foot`)

`q-drawer bordered`, ancho fijo 248px, fondo `--color-surface`. Plegable en cualquier ancho de
pantalla mediante el botón de menú de la cabecera; el estado (abierto/plegado) se recuerda en
`localStorage` (`capataz.drawerOpen`) y solo aplica a anchos no móviles — en móvil el drawer sigue
siendo un overlay que arranca siempre cerrado. Título de sección en mayúsculas (`drawer-title`).
Item activo: fondo `rgba(100, 170, 176, 0.15)` (teal de marca al 15% de opacidad — **no** varía por
tema, mismo valor rgba en claro y oscuro) + texto `--color-accent-text`. Pie con chip `outline` de
usuario y una nota de una línea sobre dónde se aplica la autorización real.

### 8.3 Cabecera de página (`.page-header`, `.eyebrow`, `.page h1`)

Patrón: eyebrow (kicker) → `h1` → párrafo descriptivo opcional (`max-width: 65ch`,
`color: var(--color-text-muted)`) → acciones a la derecha (botones/selects). Mismo patrón para
`.detail-header` en páginas de detalle, con `border-bottom` adicional.

### 8.4 Tarjeta de servicio (`components/ServiceCard.vue`, clase `.service-card`)

Estructura: icono de servicio + badge de estado (clicable si `canRefresh`, con spinner mientras
refresca) arriba; `h2` + descripción truncada (`text-overflow: ellipsis`, una línea); chips de
grupo/entorno (`.meta`); línea de stack de Portainer; fila de botones de acción redondos
(`round dense flat`, deshabilitados si el rol no autoriza o la acción está inactiva). Toda la
tarjeta es un enlace (`.card-link` con `position: absolute; inset: 0`) salvo los controles
interactivos, que llevan `z-index: 2` y `@click.stop` para no disparar la navegación.

### 8.5 Panel (`.panel`, usado en detail/execution/catalog)

Mismo tratamiento visual que `.service-card` (borde + fondo `--color-surface` + `--radius-md`)
pero sin el link envolvente; `h2` interno sin margen superior. Es el contenedor genérico para
bloques de contenido en páginas de detalle ("Estado por contenedor", "Acciones permitidas",
"Observabilidad", "Últimas ejecuciones", etc.).

### 8.6 Badges de estado

Dos componentes, mismo patrón visual (`q-badge` + clase `.status-badge`: `inline-flex`,
`padding: 6px 8px`, `font-weight: 600`), tablas de color/label/icono distintas:

**`ServiceStatusBadge.vue`** (`status: ServiceStatus`):

| Estado | Color Quasar | Label | Icono |
|---|---|---|---|
| `healthy` | `positive` | Operativo | `check_circle` |
| `degraded` | `warning` | Degradado | `warning` |
| `down` | `negative` | Caído | `cancel` |
| `maintenance` | `info` | Mantenimiento | `build` |
| `unknown` (o sin dato) | `grey-7` | Desconocido | `help` |

Muestra `q-spinner` en vez de icono mientras `loading`. Incluye siempre un `<span class="sr-only">`
con el estado en texto para lectores de pantalla, además del icono+label visibles.

**`ExecutionStatusBadge.vue`** (`status: ExecutionStatus`):

| Estado | Color Quasar | Label |
|---|---|---|
| `queued` | `grey-7` | En cola |
| `running` | `primary` (azul Quasar) | En curso |
| `succeeded` | `positive` | Correcta |
| `failed` | `negative` | Fallida |
| `cancelled` | `grey-7` | Cancelada |
| `timed_out` | `warning` | Agotó tiempo |
| `rejected` | `negative` | Rechazada |

### 8.7 Diálogo de confirmación crítica (`components/CriticalConfirmDialog.vue`)

`q-dialog persistent` (no se cierra al hacer clic fuera — obliga a decidir). Cabecera con icono
`warning` rojo 28px + título "Confirmar acción crítica" + subtítulo `servicio · acción`. Cuerpo
con texto de advertencia fijo + `q-input outlined autogrow` obligatorio para el motivo (regla de
validación explícita: `Boolean(value?.trim())`). Acciones: "Cancelar" (`flat`) y "Ejecutar acción
crítica" (`color="negative"`, deshabilitado hasta que el motivo tenga contenido no vacío).
Ancho fijo `min(100%, 540px)` vía `.confirm-card`/`.form-card`.

### 8.8 Banners de estado (`.error-banner`, `.success-banner`)

`.error-banner`: fondo `rgba(150, 40, 40, 0.25)`, borde `rgba(225, 128, 128, 0.5)`, texto
`#ffe5e5` en oscuro — **sobrescrito** a `#7a1f1f` bajo `body.body--light` porque el rosa pálido
es ilegible sobre fondo claro (comentario explícito en el código; es la única combinación de
color con override específico de tema fuera del bloque de variables). `.success-banner`: fondo
`rgba(95, 157, 88, 0.2)`, borde `rgba(138, 196, 125, 0.5)`, sin override de texto por tema (usa
`--color-text` normal).

### 8.9 Bloque de log de ejecución (`.event-log`)

Fondo `--color-bg` (no `--color-surface` — más oscuro/plano que una tarjeta, efecto "consola"),
borde `--color-border`, `--radius-md`, fuente monoespaciada, `max-height: 320px` con scroll,
`white-space: pre-wrap` + `overflow-wrap: break-word` para no romper el layout con líneas largas.
Todo el contenido llega ya saneado desde el runner (`sanitize_text`) antes de persistirse — el
frontend no filtra nada, solo formatea.

### 8.10 Formularios / inputs

`q-input` / `q-select` siempre `outlined`; color de borde de campo forzado a `--color-border`
(`.q-field--outlined .q-field__control:before`) y color de label/valor nativo a
`--color-text-muted` — overrides necesarios porque el tema por defecto de Quasar no conoce las
variables del proyecto. `AutoRefreshSelect.vue` es el patrón de referencia para un `q-select`
`dense outlined options-dense` con tooltip descriptivo y ancho fijo pequeño (90px).

### 8.11 Tablas (`Auditoría`, `Ejecuciones`)

`q-table` estándar de Quasar; el único override propio es el color de enlace dentro de celdas
(`.q-table a { color: var(--color-accent-text); }`). Los badges de estado dentro de tabla
reutilizan `ExecutionStatusBadge`/colores semánticos de Quasar, no un estilo de tabla aparte.

### 8.12 Chips

`q-chip dense` para metadatos "sólidos" (p. ej. grupo de servicio), `q-chip dense outline` para
metadatos secundarios (p. ej. entorno) — el par sólido/outline es el patrón para distinguir
"dato primario" de "dato contextual" dentro de la misma fila de metadatos (`.meta`).

### 8.13 Estado vacío y skeleton

`.empty-state`: bloque centrado (`min-height: 300px`, flex column, texto centrado), `h2` interno
en `--color-text` (no muted, a diferencia del resto del bloque que sí usa `--color-text-muted`)
para que el mensaje principal destaque. `.skeleton-card`: mismo `--radius-md` que las tarjetas
reales, para que el layout no salte al cargar.

### 8.14 Auth (`.auth-shell`, `.auth-card`)

Pantalla de login/callback: shell centrado a pantalla completa, tarjeta de `max-width: 380px`
con `--radius-lg` (el único uso de ese radio), `h1` con la escala `--text-xl`, banner de error
interno con padding/radio propios ajustados para encajar dentro de la tarjeta.

## 9. Movimiento

No hay transiciones/animaciones personalizadas definidas en `app.scss` más allá de las que trae
Quasar por defecto en sus propios componentes (`q-dialog`, `q-menu`, etc.). Sí hay una regla de
accesibilidad global: bajo `prefers-reduced-motion: reduce`, todas las animaciones/transiciones
(propias y de Quasar) se fuerzan a `0.01ms`. Cualquier animación nueva debe respetar esta regla
automáticamente (hereda de `*`/`*::before`/`*::after`) — no hace falta añadir excepciones por
componente.

## 10. Accesibilidad — convenciones ya presentes

- `.skip-link`: enlace "saltar al contenido" visualmente oculto hasta recibir foco, salta a
  `#main-content`.
- `:focus-visible` global: contorno de 2px en `--color-primary` (el teal de marca, no el azul de
  Quasar) con `outline-offset: 3px` — consistente en ambos temas porque `--color-primary` está
  definido en los dos.
- `.sr-only`: patrón estándar de ocultación visual accesible, usado para anotar estado adicional
  en los badges (p. ej. "`: estado healthy`" tras el label visible "Operativo").
  labels ARIA explícitos en botones icon-only (`aria-label` en toggle de tema, botón de refrescar
  estado, botones de acción de tarjeta que solo muestran icono).
- Textos alternativos de estado nunca dependen solo del color: cada badge de estado combina
  color + icono + texto (nunca solo color), y el estado de servicio añade además el `sr-only`.

## 11. Idioma y tono de contenido

Toda la interfaz está en español (es-ES), incluidos labels, mensajes de validación y formato de
fecha/hora (`toLocaleTimeString('es-ES', ...)`). Tono: directo, de operación/consola, sin
signos de exclamación ni lenguaje de marketing — p. ej. "Gestiona definiciones declarativas;
nunca comandos libres ni secretos." Mantén ese registro al añadir texto nuevo.

## 12. Mapa de archivos

| Qué | Dónde |
|---|---|
| Tokens y estilos globales | `frontend/src/styles/app.scss` |
| Config de Quasar (fuentes/plugins, sin overrides de marca) | `frontend/quasar.config.ts` |
| Carga de fuentes | `frontend/index.html` |
| Carga de favicon | `frontend/index.html` (`<link rel="icon">` etc.) |
| Favicon (SVG + fallbacks PNG) | `frontend/public/favicon.svg`, `favicon-32.png`, `apple-touch-icon.png` |
| Fuente vectorial del logo (búho) | `frontend/design-system/capataz-logo.icon.svg` |
| Layout de app (header/drawer/toggle de tema/logo inline) | `frontend/src/layouts/AppLayout.vue` |
| Internacionalización (vue-i18n, 8 idiomas, detección de navegador + persistencia) | `frontend/src/i18n/` |
| Selector de idioma (cabecera) | `frontend/src/components/LanguageSelector.vue` |
| Badges de estado | `frontend/src/components/ServiceStatusBadge.vue`, `ExecutionStatusBadge.vue` |
| Tarjeta de servicio | `frontend/src/components/ServiceCard.vue` |
| Diálogo de confirmación crítica | `frontend/src/components/CriticalConfirmDialog.vue` |
| Select de autoactualización | `frontend/src/components/AutoRefreshSelect.vue` |
| Páginas (patrones de página/panel/tabla) | `frontend/src/pages/*.vue` |
