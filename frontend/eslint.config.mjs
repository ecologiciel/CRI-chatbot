import nextVitals from "eslint-config-next/core-web-vitals";

// Next 16 enables React Compiler diagnostics that were not part of the
// project's previous lint contract. Keep the established Core Web Vitals
// checks blocking while the existing component patterns are migrated safely.
const config = [
  ...nextVitals,
  {
    rules: {
      "react-hooks/incompatible-library": "off",
      "react-hooks/immutability": "off",
      "react-hooks/purity": "off",
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default config;
