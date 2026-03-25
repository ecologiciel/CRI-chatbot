---
name: cri-design-system
description: |
  Use this skill when creating ANY frontend component, page, or UI element for the CRI back-office.
  Triggers: any mention of 'component', 'page', 'UI', 'interface', 'dashboard', 'form', 'table',
  'chart', 'sidebar', 'layout', 'modal', 'button', 'card', 'Next.js page', 'React component',
  'TailwindCSS', 'shadcn', 'design', 'theme', 'RTL', 'arabe', 'Arabic layout', or any work
  in the frontend/ directory. This skill enforces the "Modern Warm" design direction with
  terracotta & sable palette. Do NOT deviate from these specs without explicit discussion.
  FORBIDDEN: dark mode, gradients, purple/blue/neon colors, Space Grotesk, Outfit fonts.
---

# CRI Design System — "Modern Warm" (Terracotta & Sable)

## Design Direction

**Inspired by Morocco.** Warm earth tones, professional yet approachable. The back-office
serves CRI administrators managing investment dossiers — it must feel institutional,
trustworthy, and efficient. No trendy startup aesthetics.

## 1. Color System

### 1.1 CSS Variables (shadcn/ui Theme)

```css
:root {
  /* Primary — Terracotta */
  --primary: 16 55% 53%;           /* #C4704B */
  --primary-foreground: 0 0% 100%;

  /* Secondary — Sable */
  --secondary: 28 50% 64%;          /* #D4A574 */
  --secondary-foreground: 0 0% 10%;

  /* Background — Crème */
  --background: 30 33% 97%;         /* #FAF7F2 */
  --foreground: 0 0% 10%;

  /* Cards */
  --card: 0 0% 100%;
  --card-foreground: 0 0% 10%;

  /* Muted */
  --muted: 30 10% 93%;
  --muted-foreground: 20 12% 37%;

  /* Border */
  --border: 30 12% 90%;

  /* Focus ring */
  --ring: 16 55% 53%;

  /* Radius */
  --radius: 0.5rem;                 /* 8px */

  /* Sidebar — Dark Brown */
  --sidebar-bg: 24 33% 12%;         /* #3D2B1F */
  --sidebar-fg: 30 20% 90%;

  /* Tenant accent (overridden per tenant) */
  --tenant-accent: 16 55% 53%;      /* Default = terracotta */
}
```

### 1.2 Semantic Colors

| Role | Color | Hex | Usage |
|---|---|---|---|
| Success | Olive Green | `#5F8B5F` | Dossier approved, sync complete |
| Warning | Amber | `#C4944B` | Quota threshold, pending review |
| Error | Terracotta Red | `#B5544B` | Failed operations, validation errors |
| Info | Steel Blue | `#5B7A8B` | Neutral information, tips |
| Olive | Muted Green | `#7A8B5F` | Tags, secondary indicators |

### 1.3 FORBIDDEN Colors

Never use: bright blue (#0066FF), violet/purple, neon green, pure black backgrounds,
gradients of any kind, glassmorphism, or any color outside this palette.

## 2. Typography

### 2.1 Font Stack

```tsx
// app/layout.tsx
import { Plus_Jakarta_Sans, Inter } from "next/font/google";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-heading",
  weight: ["600", "700"],
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-body",
  weight: ["400", "500"],
});

// For Arabic: load Noto Sans Arabic
// <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@400;500;600;700" rel="stylesheet">
```

### 2.2 Type Scale

| Element | Font | Weight | Size | Tailwind |
|---|---|---|---|---|
| Display/H1 | Plus Jakarta Sans | 700 (bold) | 28-32px | `font-heading text-3xl font-bold` |
| H2 | Plus Jakarta Sans | 600 (semibold) | 22-24px | `font-heading text-2xl font-semibold` |
| H3 | Plus Jakarta Sans | 600 (semibold) | 18-20px | `font-heading text-lg font-semibold` |
| Body | Inter | 400 (regular) | 14-15px | `font-body text-sm` |
| Body emphasis | Inter | 500 (medium) | 14-15px | `font-body text-sm font-medium` |
| Small/Caption | Inter | 400 | 12-13px | `font-body text-xs` |
| Monospace | JetBrains Mono | 400 | 13px | `font-mono text-xs` |
| Arabic body | Noto Sans Arabic | 400-700 | Same scale | `font-arabic` |

**FORBIDDEN fonts:** Space Grotesk, Outfit, or any other "creative" typeface.

## 3. Layout Structure

### 3.1 Main Layout

```
┌──────────────────────────────────────────────┐
│ Sidebar (240px / 64px collapsed)  │ Content  │
│ Background: #3D2B1F (dark brown)  │ #FAF7F2  │
│                                   │          │
│ Logo area                         │ Topbar   │
│ Nav items                         │ 56px     │
│ Active: terracotta bg opacity     │ sticky   │
│                                   │          │
│                                   │ Main     │
│                                   │ p-6      │
│                                   │          │
│ Footer: user info                 │          │
└──────────────────────────────────────────────┘
```

### 3.2 Topbar (56px, sticky)

Contains: Breadcrumb | Search (Cmd+K) | Language Switcher (FR/AR/EN) | Notifications Bell | User Avatar

```tsx
// components/layout/topbar.tsx
export function Topbar() {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b border-border bg-card px-6">
      <Breadcrumb />
      <div className="ms-auto flex items-center gap-3">
        <CommandSearch /> {/* Cmd+K */}
        <LanguageSwitcher /> {/* FR | AR | EN */}
        <NotificationBell />
        <UserAvatar />
      </div>
    </header>
  );
}
```

### 3.3 Content Area Patterns

```tsx
{/* Page header */}
<div className="flex items-center justify-between">
  <div>
    <h1 className="font-heading text-2xl font-bold text-foreground">
      Base de connaissances
    </h1>
    <p className="mt-1 text-sm text-muted-foreground">
      Gérez les documents et contenus du chatbot
    </p>
  </div>
  <Button>
    <Plus className="me-2 h-4 w-4" />
    Ajouter un document
  </Button>
</div>

{/* Stats cards row */}
<div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
  <StatsCard title="Documents" value={42} icon={FileText} />
  <StatsCard title="Chunks indexés" value={1284} icon={Database} />
  ...
</div>

{/* Main content card */}
<Card className="mt-6">
  <CardHeader>...</CardHeader>
  <CardContent>...</CardContent>
</Card>
```

## 4. Component Patterns

### 4.1 Cards

```tsx
<Card className="shadow-card">
  {/* shadow-card: 0 1px 3px rgba(61,43,31,0.08) */}
  <CardHeader className="pb-3">
    <CardTitle className="font-heading text-lg font-semibold">
      Conversations actives
    </CardTitle>
    <CardDescription>12 conversations en cours</CardDescription>
  </CardHeader>
  <CardContent>...</CardContent>
</Card>
```

### 4.2 Tables (TanStack Table v8 + shadcn)

```tsx
{/* Table with tenant-scoped data */}
<Table>
  <TableHeader>
    <TableRow className="hover:bg-muted/50">
      <TableHead className="font-medium">N° Dossier</TableHead>
      <TableHead>Investisseur</TableHead>
      <TableHead>Statut</TableHead>
      <TableHead className="text-end">Actions</TableHead>
    </TableRow>
  </TableHeader>
  <TableBody>
    {dossiers.map((d) => (
      <TableRow key={d.id}>
        <TableCell className="font-mono text-xs">{d.numero}</TableCell>
        <TableCell>{d.contact_name}</TableCell>
        <TableCell>
          <StatusBadge status={d.statut} />
        </TableCell>
        <TableCell className="text-end">
          <DropdownMenu>...</DropdownMenu>
        </TableCell>
      </TableRow>
    ))}
  </TableBody>
</Table>
```

### 4.3 Status Badges

```tsx
const STATUS_STYLES = {
  en_cours:    "bg-amber-100 text-amber-800 border-amber-200",
  validé:      "bg-emerald-100 text-emerald-800 border-emerald-200",
  rejeté:      "bg-red-100 text-red-800 border-red-200",
  en_attente:  "bg-slate-100 text-slate-700 border-slate-200",
  complément:  "bg-blue-100 text-blue-800 border-blue-200",
} as const;

function StatusBadge({ status }: { status: keyof typeof STATUS_STYLES }) {
  return (
    <span className={cn(
      "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
      STATUS_STYLES[status],
    )}>
      {status.replace("_", " ")}
    </span>
  );
}
```

### 4.4 Charts (Recharts)

```tsx
const CHART_COLORS = {
  terracotta: "#C4704B",
  sable: "#D4A574",
  olive: "#7A8B5F",
  info: "#5B7A8B",
  success: "#5F8B5F",
  warning: "#C4944B",
};

// FORBIDDEN: bright blue, purple, neon, or any color outside this palette

<ResponsiveContainer width="100%" height={300}>
  <BarChart data={data}>
    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
    <XAxis dataKey="month" tick={{ fontSize: 12 }} />
    <YAxis tick={{ fontSize: 12 }} />
    <Tooltip />
    <Bar dataKey="conversations" fill={CHART_COLORS.terracotta} radius={[4, 4, 0, 0]} />
    <Bar dataKey="resolved" fill={CHART_COLORS.olive} radius={[4, 4, 0, 0]} />
  </BarChart>
</ResponsiveContainer>
```

### 4.5 Icons (Lucide React)

```tsx
import { FileText, Users, MessageSquare, Settings } from "lucide-react";

// Always: size 20px (h-5 w-5), stroke-width 1.75
<FileText className="h-5 w-5" strokeWidth={1.75} />
```

## 5. RTL Support (Arabic)

### 5.1 HTML Direction

```tsx
// app/layout.tsx
export default function RootLayout({ children, params }: { children: ReactNode; params: { lang: string } }) {
  const dir = params.lang === "ar" ? "rtl" : "ltr";
  return (
    <html lang={params.lang} dir={dir}>
      <body className={cn(
        inter.variable,
        plusJakarta.variable,
        params.lang === "ar" && "font-arabic",
      )}>
        {children}
      </body>
    </html>
  );
}
```

### 5.2 Logical Properties (MANDATORY)

```tsx
{/* ✅ CORRECT — Uses logical properties */}
<div className="ms-4 me-2 ps-3 pe-3 text-start">
  <ChevronRight className="h-4 w-4 rtl:rotate-180" />
</div>

{/* ❌ FORBIDDEN — Physical properties break RTL */}
<div className="ml-4 mr-2 pl-3 pr-3 text-left">
  <ChevronRight className="h-4 w-4" />
</div>
```

### 5.3 RTL Checklist

- [ ] Sidebar flips to right side in RTL
- [ ] All `ml-*`/`mr-*` replaced with `ms-*`/`me-*`
- [ ] All `pl-*`/`pr-*` replaced with `ps-*`/`pe-*`
- [ ] All `text-left`/`text-right` replaced with `text-start`/`text-end`
- [ ] Directional icons have `rtl:rotate-180`
- [ ] Recharts Y-axis moves to right in RTL
- [ ] Toast notifications appear bottom-left in RTL
- [ ] Form labels align correctly
- [ ] Breadcrumb separator direction reverses

## 6. Accessibility (WCAG 2.1 AA)

- **Contrast**: 4.5:1 for normal text, 3:1 for large text
- **⚠️ Terracotta on white** = 4.1:1 → use ONLY for bold/large text, or darken to `#A85E3B`
- **Focus ring**: `ring-2 ring-ring ring-offset-2` (3px, terracotta, 2px offset)
- **Reduced motion**: `motion-safe:transition-all motion-reduce:transition-none`
- **Keyboard navigation**: All interactive elements reachable via Tab
- **Screen readers**: Use `sr-only` class for icon-only buttons

## 7. Multi-Tenant Theming

Each tenant can customize:
- `logo`: SVG or PNG, max 200x60px (displayed in sidebar)
- `--tenant-accent`: CSS variable for tenant brand color
- `name`: Displayed in topbar
- `favicon`: 32x32px

```tsx
// lib/tenant-theme.ts
export function applyTenantTheme(tenant: TenantConfig) {
  document.documentElement.style.setProperty(
    "--tenant-accent",
    tenant.accent_color || "16 55% 53%",
  );
}
```

**RULE**: The tenant accent NEVER replaces the terracotta palette. It is ONLY used for:
- Login page branding
- Sidebar logo area background tint
- Tenant name display

## 8. Shadows

```css
.shadow-card {
  box-shadow: 0 1px 3px rgba(61, 43, 31, 0.08);
}
.shadow-elevated {
  box-shadow: 0 4px 12px rgba(61, 43, 31, 0.12);
}
```

## 9. Spacing & Sizing Quick Reference

| Element | Value |
|---|---|
| Page padding | `p-6` (24px) |
| Card padding | `p-4` to `p-6` |
| Gap between cards | `gap-4` (16px) |
| Sidebar width | 240px expanded, 64px collapsed |
| Topbar height | 56px (`h-14`) |
| Border radius | `rounded-lg` (8px default) |
| Icon size | `h-5 w-5` (20px) |
| Button height | `h-9` (36px default) |
