import brandSymbolLight from "../../../docs/Claridez_Brand_Assets_v1.0/svg/claridez-isotipo-white.svg";
import brandLogoColor from "../../../docs/Claridez_Brand_Assets_v1.0/svg/claridez-logo-horizontal-color.svg";
import brandLogoLight from "../../../docs/Claridez_Brand_Assets_v1.0/svg/claridez-logo-horizontal-white.svg";

export function BrandLogo({ theme = "color" }: { theme?: "color" | "light" }) {
  return (
    <img
      className={`brand-logo brand-logo--${theme}`}
      src={theme === "light" ? brandLogoLight : brandLogoColor}
      alt="Claridez"
    />
  );
}

export function BrandSymbol() {
  return <img className="brand-symbol" src={brandSymbolLight} alt="" aria-hidden="true" />;
}
