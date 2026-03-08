import { GoogleGenAI } from "@google/genai";
import { Transaction } from "../types.ts";

export const getTaxInsights = async (transactions: Transaction[]) => {
  const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });

  const txSummary = transactions.slice(0, 50).map(t => ({
    date: new Date(t.timestamp).toLocaleDateString(),
    ex: t.exchange,
    type: t.type,
    asset: t.currency,
    krw: t.krwValue
  }));

  const summaryPrompt = `
    당신은 대한민국 최고의 가상자산 전문 세무사입니다. 다음 거래 내역을 분석하여 한국 투자자를 위한 맞춤형 절세 리포트를 작성하세요.
    
    데이터: ${JSON.stringify(txSummary)}
    
    분석 기준 (한국 세법):
    1. 2025년부터 가상자산 소득세 시행 예정 (세율 22%, 250만원 기본 공제).
    2. 이동평균법(Moving Average) 또는 선입선출법(FIFO) 적용 시나리오 고려.
    3. 김치 프리미엄(해외 거래소 전송)으로 인한 취득가액 산정 주의사항.
    
    요구사항:
    - [현재 상태]: 현재 수익 상황과 예상되는 과세 대상 소득 요약.
    - [위험 요소]: 거래소 간 전송 시 취득가액 증빙이 어려운 내역 지적.
    - [절세 전략]: 250만원 기본 공제를 활용하기 위해 올해 말에 취해야 할 행동 (예: 손실 확정 매도).
    - [김프 분석]: 해외 거래소 이용 시 환율 및 프리미엄으로 인한 이득/손실 분석.
    
    톤앤매너: 토스(Toss) 앱처럼 쉽고, 간결하며, 핵심 위주로 작성하세요. 전문 용어는 쉽게 풀어서 설명하세요. 마크다운 형식을 사용하세요.
  `;

  try {
    const response = await ai.models.generateContent({
      model: 'gemini-2.5-pro',
      contents: summaryPrompt,
    });
    return response.text;
  } catch (error) {
    console.error("Gemini Error:", error);
    return "### 분석을 불러올 수 없습니다\nAPI 연결 상태를 확인하거나 잠시 후 다시 시도해주세요.";
  }
};
