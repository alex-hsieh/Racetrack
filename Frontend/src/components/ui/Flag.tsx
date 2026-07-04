import { getFlagUrl } from "../../utils/countryFlags";

export default function Flag({
  name,
  fallback = "🏁",
  className,
}: {
  name?: string | null;
  fallback?: string;
  className?: string;
}) {
  const url = getFlagUrl(name);
  if (!url) {
    return (
      <span className={className} aria-hidden="true">
        {fallback}
      </span>
    );
  }
  return <img src={url} alt="" aria-hidden="true" className={className} />;
}
