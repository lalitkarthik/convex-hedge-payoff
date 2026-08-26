import Terminal from "@/components/Terminal";

/**
 * The page is a **server component** and the interactive parts below it are client
 * components — #17's answer, and the reason state lives in the tree rather than a store.
 *
 * It renders a shell and lets the client load the first chain, because in the skeleton
 * the fixtures are static files served from `public/`. When the backend exists this is
 * where the initial `/session` and `/chain` fetch belongs, so that the first paint
 * already has a chain in it.
 */
export default function Page() {
  return <Terminal />;
}
