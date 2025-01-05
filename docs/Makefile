# Documentation management with mkdocs and mike
.PHONY: clean deploy deploy-dev push list delete delete-all

# Variables
MKDOCS := mkdocs
MIKE := mike
VERSION ?= latest
ALIAS ?= latest
MESSAGE ?= "Documentation update"

clean:
	@echo "Cleaning up site..."
	rm -rf site

# Deploy a new stable version (with version number and alias "latest")
deploy:
	@if [ "$(VERSION)" = "latest" ]; then \
		echo "Error: Please specify a version number (e.g. make deploy VERSION=1.0.0)"; \
		exit 1; \
	fi
	@echo "Deploying version $(VERSION) with alias $(ALIAS)..."
	$(MIKE) deploy --update-aliases $(VERSION) $(ALIAS) --message $(MESSAGE)
	make clean

# The version name is "dev"
deploy-dev:
	@echo "Deploying development version..."
	$(MIKE) deploy dev --message "Documentation update"
	make clean

push:
	@echo "Pushing documentation to GitHub Pages..."
	git push origin gh-pages

# List all available versions
list:
	@echo "Available documentation versions:"
	$(MIKE) list

# Delete a version
delete:
	@if [ "$(VERSION)" = "latest" ]; then \
		echo "Error: Please specify a version to delete (e.g. make delete VERSION=1.0.0)"; \
		exit 1; \
	fi
	@echo "Deleting version $(VERSION)..."
	$(MIKE) delete $(VERSION)

delete-all:
	@echo "Deleting all versions..."
	$(MIKE) delete --all
