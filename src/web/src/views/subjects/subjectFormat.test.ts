import { describe, expect, it } from "vitest"
import { splitParagraphs } from "./subjectFormat"

describe("splitParagraphs", () => {
  it.each([
    ["常规空行分段", "A\n\nB\n\nC", ["A", "B", "C"]],
    ["单段无空行", "单段无空行", ["单段无空行"]],
    ["连续多空行", "A\n\n\n\nB", ["A", "B"]],
    ["边缘空白与空白段", "\nA\n\n \n\nB ", ["A", "B"]],
    ["空串", "", []],
    ["纯空白", "   \n\n  ", []],
    ["CRLF 归一", "A\r\n\r\nB", ["A", "B"]],
    ["段内单换行保留", "段内单换行\n照常保留", ["段内单换行\n照常保留"]],
  ])("%s", (_label, input, expected) => {
    expect(splitParagraphs(input)).toEqual(expected)
  })
})
