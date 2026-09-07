import XCTest
@testable import PocketOSKitTests

fileprivate extension ProjectionDecodeTests {
    @available(*, deprecated, message: "Not actually deprecated. Marked as deprecated to allow inclusion of deprecated tests (which test deprecated functionality) without warnings")
    static nonisolated(unsafe) let __allTests__ProjectionDecodeTests = [
        ("testDecisionsProjectionDecodesGovernanceStatuses", testDecisionsProjectionDecodesGovernanceStatuses),
        ("testHealthProjection", testHealthProjection),
        ("testShadowProjectionDecodesAndCarriesExplicitAuthorityBoundary", testShadowProjectionDecodesAndCarriesExplicitAuthorityBoundary),
        ("testStateProjectionDecodesLedgerWithHashChain", testStateProjectionDecodesLedgerWithHashChain),
        ("testTwinProjectionDecodesAndCarriesEpistemicStates", testTwinProjectionDecodesAndCarriesEpistemicStates)
    ]
}
@available(*, deprecated, message: "Not actually deprecated. Marked as deprecated to allow inclusion of deprecated tests (which test deprecated functionality) without warnings")
func __PocketOSKitTests__allTests() -> [XCTestCaseEntry] {
    return [
        testCase(ProjectionDecodeTests.__allTests__ProjectionDecodeTests)
    ]
}