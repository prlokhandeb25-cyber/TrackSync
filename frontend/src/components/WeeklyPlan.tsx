import GapProof from './GapProof'
import ClusterProof from './ClusterProof'
import ScheduleView from './ScheduleView'
import RerouteAdvisor from './RerouteAdvisor'
import PlanCheck from './PlanCheck'

/* Weekly block plan: the same three steps the system takes for every job, in order, each backed
   by what it really computed - find the gaps, group the jobs, schedule them - then the plan. */

export default function WeeklyPlan() {
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="grid two" style={{ alignItems: 'start' }}>
        <GapProof />
        <ClusterProof />
      </div>
      <ScheduleView />
      <PlanCheck />
      <RerouteAdvisor />
    </div>
  )
}
