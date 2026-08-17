// Pulls @testing-library/jest-dom's global Jest matcher type augmentations
// (toBeInTheDocument, toHaveClass, etc.) into the tsc program. jest.setup.js
// imports "@testing-library/jest-dom" for its runtime side effect (registering
// the matchers with Jest), but that file is plain JS and tsconfig's "include"
// only picks up **/*.ts and **/*.tsx, so it never contributes ambient types.
// Every test file across the suite uses these matchers without importing
// jest-dom itself, relying on this augmentation being present somewhere in
// the compiled program -- this file is that somewhere.
/// <reference types="@testing-library/jest-dom" />
