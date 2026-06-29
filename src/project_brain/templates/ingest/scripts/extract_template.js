// 적재 추출 템플릿(채워넣기 골격). 고정 코드 아님 — 적재마다 GROUPS/프롬프트 슬롯을 채운다.
// 출력: [{group, title, extract:{atoms}, verify:{corrected_atoms}}] (assemble_notes가 읽는 형태).
// CASE: verify가 corrected_atoms를 비워 반환할 수 있음 → 빈배열 폴백 방어(assemble_notes가 extract.atoms로 폴백). (근거: main-map 2026-06-25)

// 스키마 4종(추출 atom이 따라야 할 형태) — 프롬프트에 그대로 넣는다.
const SCHEMAS = {
  mapping: { mapping_key: "kebab", canonical_summary: "", meaning: "", boundary: "" },
  glossary_term: { term_key: "kebab", term: "", definition: "" },
  code_anchor: { path: "Classes/...", symbol: "Class::method", quote: "// 코드 인용" },
  // 결정은 코드가 아니라 사람 판정 → domain_spec.DECISIONS에 직접 쓴다(여기서 추출 안 함).
  decision_note: { key: "kebab", decision_type: "improvement|qa_issue|...", title: "", summary: "",
                   decision: "", affects: ["mapping_key"], evidence: [{ type: "commit|jira|pr", ref: "", summary: "" }] },
};

// GROUPS: 적재마다 채운다. 의미 경계(사람 판정 — 금지선). 각 group은 extract→verify 1회.
const GROUPS = [
  // { name: "<group-name>", focus: "<이 그룹이 뽑을 의미 범위>" },
];

// 각 group 처리: extract(코드→atom 후보) → verify(반박·보정). 프롬프트 슬롯은 적재마다 채운다.
async function runGroup(group) {
  const extractPrompt = `/* TODO: ${group.focus} 에서 SCHEMAS 형태로 의미 원자 추출 */`;
  const extract = await llmExtract(extractPrompt);          // TODO: 추출 호출 슬롯
  const verifyPrompt = `/* TODO: 위 atoms를 코드 대조로 반박·보정 */`;
  const verify = await llmVerify(verifyPrompt, extract);    // TODO: 검증 호출 슬롯
  // CASE 폴백 방어: verify가 비면 corrected_atoms를 비워 두고 assemble_notes가 extract.atoms로 폴백.
  return { group: group.name, title: group.focus,
           extract: { atoms: (extract && extract.atoms) || [] },
           verify: { corrected_atoms: (verify && verify.corrected_atoms) || [] } };
}

async function main() {
  const out = [];
  for (const g of GROUPS) out.push(await runGroup(g));
  console.log(JSON.stringify(out, null, 2));   // assemble_notes.py가 읽는 verify.json
}
// 추출/검증 호출(llmExtract/llmVerify)은 실행 환경(Workflow agent 등)에서 주입. 이 파일은 골격.
module.exports = { SCHEMAS, GROUPS, runGroup, main };
