.PHONY: project build test open
DESTINATION ?= generic/platform=iOS Simulator
project:
	xcodegen generate
build: project
	xcodebuild -project Dots.xcodeproj -scheme Dots -destination '$(DESTINATION)' -derivedDataPath DerivedData build
test: project
	xcodebuild -project Dots.xcodeproj -scheme Dots -destination '$(DESTINATION)' -derivedDataPath DerivedData test
open: project
	open Dots.xcodeproj
