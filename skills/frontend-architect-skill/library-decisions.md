# Library Decisions (Pre-Evaluated)

## Core Stack (Locked)

| Concern | Library | Version | Why This Over Alternatives |
|---------|---------|---------|---------------------------|
| Framework | Next.js | 16.1 | App Router, SSR, middleware, Turbopack |
| React | React | 19.1 | Concurrent, server components |
| Language | TypeScript | 5 | Strict mode, path aliases |
| Styling | Tailwind CSS | 4 | OKLCH colors, utility-first |
| Components | shadcn/ui | latest | 61+ Radix-based, customizable |
| Client State | Zustand | 5 | Lightweight (2KB), devtools, persist |
| Server State | TanStack Query | 5 | Caching, mutations, devtools |
| Tables | TanStack Table | 8 | Headless, composable, filtering |
| Forms | react-hook-form | 7 | Uncontrolled, fast, low re-renders |
| Validation | Zod | 4 | TypeScript-native, tree-shakeable |
| Auth | Better Auth | 1.4 | Session cookies, OAuth, middleware |
| i18n | next-intl | 4 | Static rendering, type-safe |
| Icons | lucide-react | 0.533 | Tree-shake, consistent, 1000+ icons |
| Toasts | sonner | 2 | Beautiful, accessible, stackable |
| DnD | @dnd-kit | 6 | Composable, accessible, performant |
| Date | date-fns | 4 | Tree-shakeable, immutable |
| Charts | recharts | 2 | Composable, responsive |
| CSV Parse | papaparse | 5 | Streaming, encoding detection |
| Excel Parse | xlsx (SheetJS) | latest | Fast, multi-format |
| Class Utils | clsx + tailwind-merge | latest | `cn()` utility for conditional classes |
| Carousel | embla-carousel | 8 | Lightweight, extensible |
| Panels | react-resizable-panels | 4 | Accessible, keyboard support |
| OTP | input-otp | 1 | Accessible, customizable |
| Command | cmdk | 1 | Command palette |
| Drawer | vaul | 1 | Mobile drawer |

## When NOT to Use These

| Don't Use | Use Instead | When |
|-----------|-------------|------|
| Redux | Zustand | Always. Redux is overkill for this stack. |
| Axios | fetchApi() wrapper | Always. Native fetch + our adapter pattern. |
| MUI/Ant Design | shadcn/ui | Always. We don't use component library CSS. |
| Formik | react-hook-form | Always. RHF is faster and lighter. |
| Yup | Zod | Always. Zod has better TS inference. |
| moment.js | date-fns | Always. date-fns is tree-shakeable. |
| styled-components | Tailwind | Always. Utility-first approach. |
| SWR | TanStack Query | Always. TQ has better mutation support. |
| react-dnd | @dnd-kit | Always. DnD-kit is more composable. |

## Adding New Libraries

Before adding ANY new dependency:

1. Check if shadcn/ui already has a component for it
2. Check if the existing stack handles the use case
3. If genuinely new: compare >=3 candidates by:
   - Bundle size (check bundlephobia.com)
   - TypeScript support
   - Maintenance (last release, open issues)
   - Weekly downloads
   - License (MIT preferred)
4. Document the decision in this file
5. Only then install
