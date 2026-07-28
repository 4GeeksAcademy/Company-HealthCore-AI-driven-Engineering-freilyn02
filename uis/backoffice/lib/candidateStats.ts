export interface CandidateStatsInput {
    totalCandidates: number;
    selected: number;
    discarded: number;
  }
  
  export interface CandidateStatsResult {
    totalCandidates: number;
    selectionRate: number;
    discardRate: number;
  }
  
  export function calculateCandidateStats(
    input: CandidateStatsInput
  ): CandidateStatsResult {
    const { totalCandidates, selected, discarded } = input;
  
    if (totalCandidates === 0) {
      return { totalCandidates: 0, selectionRate: 0, discardRate: 0 };
    }
  
    return {
      totalCandidates,
      selectionRate: Number(((selected / totalCandidates) * 100).toFixed(1)),
      discardRate: Number(((discarded / totalCandidates) * 100).toFixed(1)),
    };
  }