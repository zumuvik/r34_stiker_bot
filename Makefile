.PHONY: deploy restart logs status

deploy:        ## Обновить код на сервере и перезапустить бота
	git pull
	tar czf /tmp/r34_bot_deploy.tar.gz \
		--exclude=.venv --exclude=venv --exclude=__pycache__ \
		--exclude=__pytest_cache__ --exclude=.git --exclude='*.db*' \
		--exclude='*.log' --exclude=.env \
		.
	ssh -o StrictHostKeyChecking=accept-new zumuvik@45.13.237.210 \
		'tar xzf - -C ~/r34_stiker_bot/' < /tmp/r34_bot_deploy.tar.gz
	ssh -o StrictHostKeyChecking=accept-new zumuvik@45.13.237.210 \
		'bash -c "systemctl --user daemon-reload && systemctl --user restart r34-bot.service"'
	rm -f /tmp/r34_bot_deploy.tar.gz
	@echo "✓ Бот обновлён и перезапущен"

restart:       ## Перезапустить бота на сервере
	ssh zumuvik@45.13.237.210 'systemctl --user restart r34-bot.service'
	@echo "✓ Бот перезапущен"

logs:          ## Смотреть логи бота на сервере
	ssh zumuvik@45.13.237.210 'journalctl --user -u r34-bot.service -f'

status:        ## Статус бота на сервере
	ssh zumuvik@45.13.237.210 'systemctl --user status r34-bot.service'

help:          ## Показать все команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
