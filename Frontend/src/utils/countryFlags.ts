// Maps race countries / driver nationalities to local flag SVG assets.
// Flags are vendored from the `flag-icons` package (src/assets/flags) rather
// than rendered as emoji, since Windows Chrome does not render flag emoji
// (shows the raw two-letter code instead) while other browsers do.
const flagModules = import.meta.glob<string>("../assets/flags/*.svg", {
  eager: true,
  import: "default",
  query: "?url",
});

const FLAG_BY_ISO: Record<string, string> = {};
for (const path in flagModules) {
  const match = path.match(/([a-z]{2})\.svg$/);
  if (match) FLAG_BY_ISO[match[1]] = flagModules[path];
}

const NAME_TO_ISO: Record<string, string> = {
  bahrain: "bh",
  "saudi arabia": "sa",
  australia: "au", australian: "au",
  japan: "jp", japanese: "jp",
  china: "cn", chinese: "cn",
  usa: "us", "united states": "us", america: "us", american: "us",
  "las vegas": "us", miami: "us",
  italy: "it", italian: "it",
  monaco: "mc", monegasque: "mc",
  canada: "ca", canadian: "ca",
  "united kingdom": "gb", "great britain": "gb", uk: "gb", british: "gb",
  belgium: "be",
  netherlands: "nl", dutch: "nl",
  azerbaijan: "az",
  singapore: "sg",
  mexico: "mx", mexican: "mx",
  brazil: "br", brazilian: "br",
  qatar: "qa",
  "abu dhabi": "ae", uae: "ae",
  spain: "es", spanish: "es",
  austria: "at",
  hungary: "hu",
  france: "fr", french: "fr",
  russia: "ru",
  turkey: "tr",
  germany: "de", german: "de",
  finland: "fi", finnish: "fi",
  denmark: "dk", danish: "dk",
  thailand: "th", thai: "th",
  argentina: "ar", argentinian: "ar",
  "new zealand": "nz", "new zealander": "nz",
};

export function getFlagUrl(name?: string | null): string | null {
  if (!name) return null;
  const iso = NAME_TO_ISO[name.trim().toLowerCase()];
  if (!iso) return null;
  return FLAG_BY_ISO[iso] ?? null;
}
