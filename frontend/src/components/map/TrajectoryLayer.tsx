import { CircleMarker, Polyline, Popup } from 'react-leaflet'
import { CATEGORY_COLOR, CATEGORY_LABEL } from '../../safety/landingSafety'
import { useResultsStore } from '../../store/resultsStore'
import { utcIsoToJstDisplay } from '../../time/jst'
import type { Flight } from '../../api/tawhiriTypes'

function flightPath(f: Flight): [number, number][] {
  return [...f.ascent, ...f.descent].map((p) => [p.latitude, p.longitude])
}

function FlightLine({
  flight,
  color = '#000000',
  weight = 2,
  withMarkers = true,
}: {
  flight: Flight
  color?: string
  weight?: number
  withMarkers?: boolean
}) {
  return (
    <>
      <Polyline positions={flightPath(flight)} color={color} weight={weight} />
      {withMarkers && (
        <>
          <CircleMarker
            center={[flight.launch.latitude, flight.launch.longitude]}
            radius={6}
            pathOptions={{ color: '#1976d2', fillOpacity: 0.9 }}
          >
            <Popup>
              打上 {utcIsoToJstDisplay(flight.launch.datetime)} JST
            </Popup>
          </CircleMarker>
          {flight.burst && (
            <CircleMarker
              center={[flight.burst.latitude, flight.burst.longitude]}
              radius={6}
              pathOptions={{ color: '#f57c00', fillOpacity: 0.9 }}
            >
              <Popup>
                バースト 高度 {Math.round(flight.burst.altitude)} m /{' '}
                {utcIsoToJstDisplay(flight.burst.datetime)} JST
              </Popup>
            </CircleMarker>
          )}
          <CircleMarker
            center={[flight.landing.latitude, flight.landing.longitude]}
            radius={6}
            pathOptions={{ color: '#d32f2f', fillOpacity: 0.9 }}
          >
            <Popup>
              着地 ({flight.landing.latitude.toFixed(4)},{' '}
              {flight.landing.longitude.toFixed(4)})<br />
              {utcIsoToJstDisplay(flight.landing.datetime)} JST
            </Popup>
          </CircleMarker>
        </>
      )}
    </>
  )
}

const TURBO_STOPS = ['#30123b', '#3e9bfe', '#46f884', '#e1dd37', '#f05b12', '#7a0403']

function turboColor(t: number): string {
  const i = Math.min(
    TURBO_STOPS.length - 1,
    Math.max(0, Math.floor(t * (TURBO_STOPS.length - 1))),
  )
  return TURBO_STOPS[i]
}

export function TrajectoryLayer() {
  const single = useResultsStore((s) => s.singleFlight)
  const hourly = useResultsStore((s) => s.hourlyResults)
  const mcSamples = useResultsStore((s) => s.mcSamples)
  const mcCentral = useResultsStore((s) => s.mcCentral)
  const mode = useResultsStore((s) => s.mode)

  const maxHour = Math.max(1, ...hourly.map((h) => h.hourOffset))

  return (
    <>
      {single && <FlightLine flight={single} />}
      {hourly.map((h) => (
        <CircleMarker
          key={h.hourOffset}
          center={[h.flight.landing.latitude, h.flight.landing.longitude]}
          radius={5}
          pathOptions={{
            fillColor: turboColor(h.hourOffset / maxHour),
            fillOpacity: 1,
            color: '#000',
            weight: 1,
          }}
        >
          <Popup>
            打上 {utcIsoToJstDisplay(h.flight.launch.datetime)} JST (+
            {h.hourOffset}h)
            <br />
            着地 ({h.flight.landing.latitude.toFixed(4)},{' '}
            {h.flight.landing.longitude.toFixed(4)})
          </Popup>
        </CircleMarker>
      ))}
      {mcSamples.map((s) => (
        <CircleMarker
          key={s.index}
          center={[s.flight.landing.latitude, s.flight.landing.longitude]}
          radius={4}
          pathOptions={{
            fillColor: s.category ? CATEGORY_COLOR[s.category] : '#7b1fa2',
            fillOpacity: 0.75,
            weight: 0,
          }}
        >
          <Popup>
            #{s.index}
            {s.category && (
              <>
                {' '}
                <b>[{CATEGORY_LABEL[s.category]}]</b>
              </>
            )}
            {mode === 'climatology' ? (
              <>
                <br />
                着地 ({s.flight.landing.latitude.toFixed(4)},{' '}
                {s.flight.landing.longitude.toFixed(4)})
              </>
            ) : (
              <>
                <br />
                上昇 {s.perturbed.ascentRate.toFixed(2)} m/s / バースト{' '}
                {Math.round(s.perturbed.burstAltitude)} m / 降下{' '}
                {s.perturbed.descentRate.toFixed(2)} m/s
              </>
            )}
          </Popup>
        </CircleMarker>
      ))}
      {mcCentral && <FlightLine flight={mcCentral} color="#d32f2f" />}
    </>
  )
}
