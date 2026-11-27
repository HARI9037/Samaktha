//! Common test utilities shared across integration tests.

// Include and re-export the parity_fixtures module from the tests directory
#[path = "../parity_fixtures.rs"]
mod parity_fixtures;
pub use parity_fixtures::*;