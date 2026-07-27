# app/telegram_bot.py

import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from app.agente import AgenteRAG
from app.config import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)

class TelegramBotManager:
    def __init__(self, agente: AgenteRAG):
        """
        Inicializa el gestor del bot inyectando la dependencia del agente RAG 
        y obteniendo el token desde config.py.
        """
        self.agente = agente
        self.token = TELEGRAM_BOT_TOKEN
        self.application = None

    async def initialize(self):
        """
        Construye la aplicación de Telegram y configura los manejadores de eventos.
        Se ejecuta durante el evento de arranque del servidor FastAPI (lifespan).
        """
        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN no configurado. El bot no se iniciará.")
            return

        try:
            logger.info("Construyendo e iniciando aplicación de Telegram...")
            self.application = ApplicationBuilder().token(self.token).build()
            
            # Configurar el manejador: escucha cualquier texto que NO sea un comando (ej. /start)
            echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message)
            self.application.add_handler(echo_handler)

            # Inicializa internamente la app de Telegram
            await self.application.initialize()
            await self.application.start()
            
            # Arranca el "polling" (consulta constante a Telegram por nuevos mensajes)
            await self.application.updater.start_polling()
            logger.info("Bot de Telegram iniciado correctamente y escuchando mensajes.")
            
        except Exception as e:
            logger.error(f"Error crítico al iniciar el bot de Telegram: {e}", exc_info=True)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Recibe un mensaje de un usuario de Telegram, se lo pasa al Agente RAG 
        y devuelve la respuesta manteniendo el historial independiente por chat.
        """
        if not update.message or not update.message.text:
            return  # Ignorar si no hay texto

        user_message = update.message.text
        # Usamos el chat_id como session_id para mantener memoria por usuario
        session_id = str(update.effective_chat.id)
        
        logger.info(f"Mensaje recibido en Telegram (Chat ID {session_id}): {user_message[:50]}...")

        # Verificar si el agente está listo antes de consultar
        if not self.agente.is_ready:
            await update.message.reply_text("El asistente está iniciando. Por favor, intenta de nuevo en unos segundos.")
            return

        # Indicar al usuario que el bot está escribiendo
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')

        try:
            # Consultar al agente RAG pasando la pregunta y el session_id
            resultado = await self.agente.chat(pregunta=user_message, session_id=session_id)
            
            # Extraer la respuesta del diccionario retornado
            respuesta = resultado.get("respuesta", "Lo siento, no he podido generar una respuesta.")
                
            await update.message.reply_text(respuesta) # Usamos Markdown para formato básico parse_mode='Markdown'
            
        except Exception as e:
            logger.error(f"Error al procesar mensaje de Telegram para sesión {session_id}: {e}", exc_info=True)
            await update.message.reply_text("Lo siento, ocurrió un error interno procesando tu consulta.")

    async def shutdown(self):
        """
        Detiene la aplicación de Telegram y el polling de forma limpia.
        Se ejecuta durante el apagado del servidor FastAPI (lifespan).
        """
        if self.application:
            logger.info("Iniciando apagado del bot de Telegram...")
            try:
                if self.application.updater:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
                logger.info("Bot de Telegram detenido correctamente.")
            except Exception as e:
                logger.error(f"Error durante el apagado del bot de Telegram: {e}", exc_info=True)