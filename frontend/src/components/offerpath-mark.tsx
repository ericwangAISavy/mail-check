import mark from "@/assets/offerpath-small.png"

/** Shared OfferPath identity; surrounding labels provide the accessible name. */
export function OfferPathMark({size = 24}: {size?: number}) {
  return <img className="offerpath-mark" src={mark} width={size} height={size} alt="" aria-hidden="true" />
}
