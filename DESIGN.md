# Design

## Theme

**Light.** Il sistema è usato in ambienti aeroportuali luminosi (schermi agli sportelli, tablet in mano, laptop personali) e da passeggeri a casa. Lo sfondo chiaro con superfici bianche e accenti navy garantisce leggibilità in condizioni di luce variabile. Nessun dark mode: non è un tool per sviluppatori, è infrastruttura operativa.

## Color Strategy

**Committed.** Il navy (`--c-navy`) porta il 40–60% delle superfici di navigazione e header. Il gold (`--c-gold`) è riservato esclusivamente alle call-to-action primarie. I neutrali sono tintati verso il brand hue (hue 245).

```css
:root {
  /* Brand primari */
  --c-navy:    oklch(17% 0.045 248);   /* #0c1b30 — header, topbar, footer */
  --c-blue:    oklch(38% 0.11 248);    /* #1a4a7a — link, icone attive */
  --c-sky:     oklch(55% 0.12 245);    /* #3a7fc1 — hover stati, progress */

  /* CTA */
  --c-gold:    oklch(70% 0.16 76);     /* #d48a14 — pulsanti primari */
  --c-gold-lt: oklch(78% 0.14 78);     /* #e8a832 — hover CTA */

  /* Superfici (neutrali tintati verso hue 245) */
  --c-bg:      oklch(96% 0.008 245);   /* #f2f5fa — sfondo pagina */
  --c-surface: oklch(98.5% 0.004 245); /* #f9fafc — card, pannelli */
  --c-border:  oklch(85% 0.012 245);   /* #c8d4e6 — linee divisorie */

  /* Testo */
  --c-ink:     oklch(16% 0.04 248);    /* #101d2e — testo primario */
  --c-muted:   oklch(48% 0.05 242);    /* #55697f — testo secondario, label */

  /* Stato (semantici) */
  --c-success: oklch(48% 0.14 152);    /* verde — prenotata pagata, gate libero */
  --c-warn:    oklch(68% 0.16 72);     /* ambra — gate occupato */
  --c-danger:  oklch(48% 0.18 27);     /* rosso — manutenzione, cancellata */
}
```

### Mapping semantico

| Stato prenotazione | Colore |
|--------------------|--------|
| prenotata | `--c-muted` (neutro) |
| pagata | `--c-success` |
| imbarcato | `--c-blue` |
| cancellata | `--c-danger` |

| Stato gate | Colore |
|------------|--------|
| libero | `--c-success` |
| occupato | `--c-warn` |
| manutenzione | `--c-danger` |

| Stato volo | Colore |
|------------|--------|
| programmato | `--c-blue` |
| partito | `--c-gold` |
| arrivato | `--c-muted` |

## Typography

**Font pairing:** "Barlow Semi Condensed" (headings, navbar, codici) + "Figtree" (body, form, tabelle). Né Inter né Roboto.

```css
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Figtree:wght@400;500;600;700&display=swap');

:root {
  --font-display: 'Barlow Semi Condensed', system-ui, sans-serif;
  --font-body:    'Figtree', system-ui, sans-serif;
}

body { font-family: var(--font-body); }
h1, h2, h3, h4, h5, h6,
.navbar-brand, .codice-volo, .gate-label { font-family: var(--font-display); }
```

### Scala tipografica (≥ 1.25 ratio tra i livelli)

| Token | Dimensione | Peso | Uso |
|-------|-----------|------|-----|
| `text-xs` | 11px | 500 | Label tabelle (uppercase, letterspacing) |
| `text-sm` | 13px | 400 | Testo secondario, sottotitoli |
| `text-base` | 15px | 400 | Testo body, form, tabelle |
| `text-md` | 17px | 500 | Elementi prominenti |
| `text-lg` | 21px | 600 | Titoli sezione |
| `text-xl` | 27px | 700 | Page titles (Barlow) |
| `text-2xl` | 36px | 700 | Codici volo, gate prominenti |

Line-length massima: 68ch su testo body.

## Elevation & Surfaces

```
Livello 0 — sfondo pagina:       var(--c-bg)
Livello 1 — card, pannelli:      var(--c-surface), box-shadow: 0 1px 3px oklch(0% 0 0 / 0.06), 0 1px 2px oklch(0% 0 0 / 0.04)
Livello 2 — dropdown, tooltip:   var(--c-surface), box-shadow: 0 4px 12px oklch(0% 0 0 / 0.10)
Livello 3 — modali:              var(--c-surface), box-shadow: 0 16px 48px oklch(0% 0 0 / 0.16)
```

Nessun blur decorativo. Le superfici sono opache.

## Spacing

Base unit: 4px. Scala:

| Token | Valore |
|-------|--------|
| `--sp-1` | 4px |
| `--sp-2` | 8px |
| `--sp-3` | 12px |
| `--sp-4` | 16px |
| `--sp-6` | 24px |
| `--sp-8` | 32px |
| `--sp-12` | 48px |
| `--sp-16` | 64px |

Spaziatura ritmica: non tutti i gap sono uguali. Sezioni separate da `--sp-12` o `--sp-16`; elementi correlati da `--sp-4` o `--sp-6`.

## Border Radius

```css
--radius-sm: 4px;    /* input, badge */
--radius-md: 8px;    /* card, dropdown */
--radius-lg: 12px;   /* modali, panel principali */
--radius-pill: 999px; /* badge status */
```

## Components

### Navbar (topbar)

- `background: var(--c-navy)`
- Altezza: 56px
- Border-bottom: 3px solid `var(--c-gold)`
- Brand: Barlow Semi Condensed 700, colore `#f9fafc`
- Link ruolo: Figtree 500, colore `oklch(80% 0.015 245)`
- Avatar/ruolo badge: pill `var(--c-gold)` con testo `var(--c-navy)`

### Pulsanti

```
Primario (CTA):   background var(--c-gold), colore var(--c-navy), font-weight 600
Secondario:       border 1.5px var(--c-blue), colore var(--c-blue), background trasparente
Pericolo:         background var(--c-danger), colore #f9fafc
Ghost:            nessun bordo, colore var(--c-muted), hover background var(--c-border)
```

Tutti con `border-radius: var(--radius-sm)`, padding `8px 16px`, `font-size: 14px`.

### Badge / Pill di stato

```
background: <colore semantico>
color: #f9fafc (o var(--c-ink) su sfondi chiari come --c-warn)
border-radius: var(--radius-pill)
padding: 2px 10px
font-size: 11px
font-weight: 600
text-transform: uppercase
letter-spacing: 0.04em
```

### Tabelle

- `<thead>`: background `var(--c-navy)`, testo `#f9fafc`, Barlow Semi Condensed 600, 11px uppercase, letterspacing 0.06em
- `<tbody>` righe: alternanza leggerissima (`var(--c-bg)` / `var(--c-surface)`)
- Hover riga: background `oklch(92% 0.012 245)` — nessun side-stripe
- Border: 1px `var(--c-border)` solo tra righe (no bordi laterali)

### Form inputs

```css
border: 1.5px solid var(--c-border);
border-radius: var(--radius-sm);
padding: 8px 12px;
font-family: var(--font-body);
font-size: 15px;
color: var(--c-ink);
background: var(--c-surface);
transition: border-color 0.15s ease-out;

&:focus {
  border-color: var(--c-sky);
  outline: 2px solid oklch(55% 0.12 245 / 0.3);
}
```

### Cards

- `background: var(--c-surface)`
- `border-radius: var(--radius-md)`
- `border: 1px solid var(--c-border)`
- Elevation livello 1
- Nessun side-stripe. Nessuna card dentro una card.
- Differenziazione tramite border-top colorato (4px, colore semantico) solo se la card rappresenta un'entità con stato.

### Modali

- Backdrop: `oklch(0% 0 0 / 0.5)` senza blur
- Pannello: `var(--c-surface)`, border-radius `var(--radius-lg)` (12px), elevation livello 3
- Header: border-bottom `1px var(--c-border)`, padding `20px 24px`
- Body: padding `24px`
- Footer: border-top `1px var(--c-border)`, padding `16px 24px`, flex row-reverse (CTA a destra)

### Toast / notifiche

- Posizione: top-right, z-index 9999
- Background: `var(--c-surface)`, border-left 4px solid (`--c-success` o `--c-danger`)
- Shadow: elevation livello 2
- Timeout: 4000ms auto-dismiss

## Motion

```css
--ease-out: cubic-bezier(0.16, 1, 0.3, 1);      /* ease-out-expo */
--ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);  /* ease-in-out-cubic */

/* Durate */
--dur-fast: 120ms;   /* hover, focus */
--dur-mid: 220ms;    /* espansioni, fade */
--dur-slow: 340ms;   /* modali, slide-in */
```

Animare solo: `opacity`, `transform`, `color`, `background-color`, `border-color`, `box-shadow`.
Mai animare: `width`, `height`, `padding`, `margin`, `top`, `left`.
Nessun bounce, nessun elastic.

## Icons

Bootstrap Icons (CDN). Dimensione standard: 16px nel body, 20px nelle navbar e heading, 24px nelle card di stato gate.
