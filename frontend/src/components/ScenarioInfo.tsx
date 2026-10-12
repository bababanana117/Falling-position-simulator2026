import { CATEGORY_COLOR, CATEGORY_LABEL } from '../safety/landingSafety'
import type { SafetyCategory } from '../safety/landingSafety'
import { useResultsStore } from '../store/resultsStore'
import { haversineM } from '../stats/landing'
import { utcIsoToJstDisplay } from '../time/jst'

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}時間 ${m}分`
}

export function ScenarioInfo() {
  const flight = useResultsStore((s) => s.singleFlight)
  const mcStats = useResultsStore((s) => s.mcStats)
  const mcSafety = useResultsStore((s) => s.mcSafety)
  const info = useResultsStore((s) => s.climatologyInfo)

  if (!flight && !mcStats) return null

  const totalSamples = mcSafety
    ? Object.values(mcSafety).reduce((a, b) => a + b, 0)
    : 0

  return (
    <div className="scenario-info">
      <h3>シナリオ情報</h3>
      {info && (
        <div className="climatology-banner" role="status">
          <b>
            統計モード（気候値・{info.label}、{info.period} 年）— 予報ではありません
          </b>
          <div>
            使った格子点: {info.cellLat.toFixed(2)}, {info.cellLon.toFixed(2)}（
            {info.cellDistanceKm.toFixed(0)} km）/ 層どうしの相関 ρ = {info.rho.toFixed(2)}
          </div>
          {info.warnings.map((w) => (
            <div key={w} className="climatology-warning">{w}</div>
          ))}
        </div>
      )}
      {flight && (
        <dl>
          <dt>着地予測</dt>
          <dd>
            {flight.landing.latitude.toFixed(4)},{' '}
            {flight.landing.longitude.toFixed(4)}
          </dd>
          <dt>着地時刻 (JST)</dt>
          <dd>{utcIsoToJstDisplay(flight.landing.datetime)}</dd>
          <dt>飛行距離</dt>
          <dd>
            {(
              haversineM(
                { lat: flight.launch.latitude, lon: flight.launch.longitude },
                { lat: flight.landing.latitude, lon: flight.landing.longitude },
              ) / 1000
            ).toFixed(1)}{' '}
            km
          </dd>
          <dt>飛行時間</dt>
          <dd>{formatDuration(flight.flightTimeS)}</dd>
        </dl>
      )}
      {mcStats && (
        <dl>
          <dt>平均着地点</dt>
          <dd>
            {mcStats.mean.lat.toFixed(4)}, {mcStats.mean.lon.toFixed(4)}
          </dd>
          <dt>50% / 90% / 95% 半径</dt>
          <dd>
            {(mcStats.percentileRadiiM[50] / 1000).toFixed(1)} /{' '}
            {(mcStats.percentileRadiiM[90] / 1000).toFixed(1)} /{' '}
            {(mcStats.percentileRadiiM[95] / 1000).toFixed(1)} km
          </dd>
          {mcSafety && totalSamples > 0 && (
            <>
              <dt>安全着地率</dt>
              <dd>
                <b>
                  {((mcSafety.safe / totalSamples) * 100).toFixed(0)}% (
                  {mcSafety.safe}/{totalSamples})
                </b>
              </dd>
              <dt>内訳</dt>
              <dd>
                {(Object.keys(mcSafety) as SafetyCategory[])
                  .filter((c) => mcSafety[c] > 0)
                  .map((c) => (
                    <span key={c} style={{ marginRight: '0.5em' }}>
                      <span style={{ color: CATEGORY_COLOR[c] }}>■</span>
                      {CATEGORY_LABEL[c]} {mcSafety[c]}
                    </span>
                  ))}
              </dd>
            </>
          )}
        </dl>
      )}
    </div>
  )
}
