"""N03 preview: 30 minute in-memory cache, stale fallback on fetch failure.
Not persistent across server restart; production N03 will refine this.
"""
from datetime import timedelta
from weather_service import JST,jst_now,interpret,validate,fetch_raw
from weather_quality import apply_quality, check_config

class ForecastCache:
    def __init__(self, ttl=timedelta(minutes=30), fetcher=fetch_raw, clock=jst_now, thresholds=None):
        self.ttl=ttl
        self.fetcher=fetcher
        self.clock=clock
        self.entries={}
        self.thresholds=check_config(thresholds)

    def get(self, latitude, longitude, when, candidate_id=None, force=False):
        now=self.clock()
        try:
            validate(latitude,longitude,when,now)
        except (ValueError,LookupError) as exc:
            return apply_quality({'status':'out_of_range' if isinstance(exc,LookupError) else 'invalid_input','error':str(exc)},None,now=now,ttl=self.ttl,thresholds=self.thresholds,last_refresh={'status':'not_attempted'})
        key=(latitude,longitude)
        entry=self.entries.get(key)
        expired=entry is None or now-entry['fetched_at'] >= self.ttl
        refetched=force or expired
        if refetched:
            try:
                raw=self.fetcher(latitude,longitude)
                entry={'raw':raw,'fetched_at':self.clock()}
                self.entries[key]=entry
                expired=False
            except Exception as exc:
                if entry is None:
                    return apply_quality({'status':'api_error','error':'予報APIを取得できません: '+str(exc),'cache_status':'unavailable'},None,now=now,ttl=self.ttl,thresholds=self.thresholds,last_refresh={'status':'failed','error_code':'api_error'},cache_hit=False)
                result=interpret(entry['raw'],latitude=latitude,longitude=longitude,when=when,candidate_id=candidate_id,fetched_at=entry['fetched_at'],now=now)
                result['cache_status']='stale'
                result['refresh_error']=str(exc)
                return apply_quality(result,entry['raw'],now=now,ttl=self.ttl,thresholds=self.thresholds,last_refresh={'status':'failed','error_code':'api_error'},cache_hit=True)
        result=interpret(entry['raw'],latitude=latitude,longitude=longitude,when=when,candidate_id=candidate_id,fetched_at=entry['fetched_at'],now=now)
        result['cache_status']='fresh'
        return apply_quality(result,entry['raw'],now=now,ttl=self.ttl,thresholds=self.thresholds,last_refresh={'status':'success' if refetched else 'not_attempted'},cache_hit=not refetched)
